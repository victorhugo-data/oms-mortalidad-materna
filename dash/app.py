"""Dashboard: muestra los datos de la OMS que guardó el recolector. Solo lee las vistas de analisis.

Se sirve con gunicorn (ver Dockerfile). Para probarlo sin Docker: python app.py
"""
import functools
import logging
import time
from datetime import datetime, timezone

import dash_ag_grid as dag
import pandas as pd
from dash import Dash, Input, Output, State, callback, ctx, dcc, html, no_update

import datos
import graficas

logging.Formatter.converter = time.gmtime
logging.basicConfig(level=logging.INFO, format="%(asctime)s UTC %(levelname)s %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S")
logging.getLogger("mysql.connector").setLevel(logging.WARNING)
log = logging.getLogger("dashboard")

INDICADOR_INICIAL = "MDG_0000000026"
LUGARES_INICIALES = ["MEX", "AMR", "GLOBAL"]
MAXIMO_LUGARES = 8
RANGO_ANCHO = 1.0          # "incertidumbre alta": el rango es más ancho que el propio valor
FALLA = "No pude leer los datos. Vuelvo a intentar en 30 segundos."
TIPOS = {"ESTIMACION": "estimación de un modelo", "REPORTADO": "dato reportado (encuestas y registros)"}
NOTAS = [
    "La mortalidad materna son estimaciones de un modelo del grupo interinstitucional de la ONU (OMS, UNICEF, "
    "UNFPA, Banco Mundial y División de Población). Cada ronda recalcula toda la serie y puede no coincidir con "
    "las cifras oficiales de cada país.",
    "Mira siempre el rango de incertidumbre: si los rangos de dos lugares se enciman, no se puede decir que uno "
    "esté peor que el otro.",
    "Los datos reportados (partos atendidos y control prenatal) vienen de encuestas y registros. Un cambio de "
    "fuente puede parecer una tendencia, y a veces la fuente solo cambia en cómo está escrita.",
    "Algunos datos de encuestas cubren varios años (por ejemplo 2013-2015); el año que se muestra es el último "
    "del periodo.",
    "En países muy pequeños, pocos casos dan saltos enormes en porcentaje.",
    "No se promedian países: los valores de las regiones y del mundo son los que calcula la OMS. Si un indicador "
    "no los trae, aquí tampoco se inventan.",
    "Que dos indicadores se muevan juntos no quiere decir que uno cause el otro.",
    "Hay tres fechas distintas: el año del dato, cuándo lo publicó la OMS y cuándo lo cargó este proyecto.",
]
ESPANOL = {  # textos de las tablas
    "page": "Página", "of": "de", "to": "a", "next": "Siguiente", "previous": "Anterior", "first": "Primera",
    "last": "Última", "more": "más", "pageSizeSelectorLabel": "Filas por página:", "noRowsToShow": "No hay datos",
    "loadingOoo": "Cargando…", "filterOoo": "Filtrar…", "contains": "Contiene", "notContains": "No contiene",
    "equals": "Igual a", "notEqual": "Distinto de", "startsWith": "Empieza con", "endsWith": "Termina con",
    "blank": "Vacío", "notBlank": "No vacío", "lessThan": "Menor que", "greaterThan": "Mayor que",
    "lessThanOrEqual": "Menor o igual a", "greaterThanOrEqual": "Mayor o igual a", "inRange": "Entre",
    "inRangeStart": "Desde", "inRangeEnd": "Hasta", "andCondition": "Y", "orCondition": "O",
    "applyFilter": "Aplicar", "resetFilter": "Restablecer", "clearFilter": "Limpiar", "cancelFilter": "Cancelar",
}
LISTA = {"select_all": "Elegir todos", "deselect_all": "Quitar todos", "selected_count": "{num_selected} elegidos",
         "search": "Buscar", "clear_search": "Borrar la búsqueda", "clear_selection": "Quitar la selección",
         "no_options_found": "No hay opciones"}  # textos de las listas desplegables
PESTANA = {"padding": "10px 16px", "border": "none", "borderBottom": "2px solid transparent",
           "background": "transparent", "color": graficas.TINTA_2, "fontWeight": 600}
PESTANA_ACTIVA = {**PESTANA, "borderBottom": f"2px solid {graficas.SERIES[0]}", "color": graficas.TINTA}


# Ayudas

def seguro(*por_defecto):
    """Si algo falla (por ejemplo, la base no responde), la página no se rompe: muestra algo vacío."""
    def envolver(funcion):
        @functools.wraps(funcion)
        def interna(*args):
            try:
                return funcion(*args)
            except Exception:
                log.exception("Falló %s", funcion.__name__)
                return por_defecto[0] if len(por_defecto) == 1 else por_defecto
        return interna
    return envolver


def fecha(valor, formato="%Y-%m-%d %H:%M UTC"):
    if valor is None or pd.isna(valor):
        return ""
    return pd.Timestamp(valor).strftime(formato)


def filas(tabla):
    """Tabla de pandas -> lista de diccionarios para la tabla de la página (sin NaN)."""
    return tabla.astype(object).where(tabla.notna(), None).to_dict("records")


def ficha_de(version, indicador):
    tabla = datos.indicadores(version)
    encontrada = tabla[tabla.codigo == indicador]
    return None if encontrada.empty else encontrada.iloc[0]


def recorte(version, indicador, anios):
    serie = datos.series(version, indicador)
    if anios:
        serie = serie[serie.anio.between(anios[0], anios[1])]
    return serie


def nombres_de(version):
    tabla = datos.ubicaciones(version)
    return {f.codigo: (f.nombre if pd.notna(f.nombre) else f.codigo) for f in tabla.itertuples()}


def campo(etiqueta, control, clase=""):
    return html.Div(className=f"campo {clase}".strip(), children=[html.Label(etiqueta, className="etiqueta"), control])


def numerica(nombre, titulo, formato=",.1f"):
    return {"field": nombre, "headerName": titulo, "filter": "agNumberColumnFilter", "type": "rightAligned",
            "minWidth": 100, "flex": 1, "useValueFormatterForExport": False,
            "valueFormatter": {"function": f"params.value == null ? '' : d3.format('{formato}')(params.value)"}}


def tabla(identificador, columnas):
    return dag.AgGrid(
        id=identificador, columnDefs=columnas, rowData=[], className="tabla",
        defaultColDef={"sortable": True, "filter": True, "resizable": True, "floatingFilter": True},
        dashGridOptions={"pagination": True, "paginationPageSize": 25, "paginationPageSizeSelector": [25, 50, 100],
                         "localeText": ESPANOL, "tooltipShowDelay": 300, "enableCellTextSelection": True},
        style={"height": "620px", "width": "100%"})


COLUMNAS_DATOS = [
    {"field": "indicador_codigo", "headerName": "Indicador", "minWidth": 150, "flex": 1},
    {"field": "ubicacion_nombre", "headerName": "Ubicación", "minWidth": 170, "flex": 2},
    {"field": "ubicacion_codigo", "headerName": "Código", "minWidth": 100, "flex": 1},
    {"field": "ubicacion_tipo", "headerName": "Tipo", "minWidth": 110, "flex": 1},
    {"field": "anio", "headerName": "Año", "filter": "agNumberColumnFilter", "minWidth": 90, "flex": 1},
    {"field": "periodo", "headerName": "Periodo", "minWidth": 110, "flex": 1},
    numerica("valor", "Valor"), numerica("valor_min", "Mínimo"), numerica("valor_max", "Máximo"),
    {"field": "fuente", "headerName": "Fuente (texto de la OMS)", "minWidth": 280, "flex": 4, "tooltipField": "fuente"},
    {"field": "fecha_publicacion_oms", "headerName": "Publicado por la OMS (UTC)", "minWidth": 200, "flex": 2},
    {"field": "fecha_carga", "headerName": "Cargado aquí (UTC)", "minWidth": 180, "flex": 2},
]
COLUMNAS_CAMBIOS = [
    {"field": "ubicacion_nombre", "headerName": "Ubicación", "minWidth": 170, "flex": 2},
    {"field": "ubicacion_tipo", "headerName": "Tipo", "minWidth": 110, "flex": 1},
    {"field": "anio", "headerName": "Año", "filter": "agNumberColumnFilter", "minWidth": 90, "flex": 1},
    numerica("valor", "Valor"),
    {"field": "antes", "headerName": "Dato anterior", "minWidth": 130, "flex": 1},
    numerica("cambio_pct", "Cambio %", "+,.1f"),
    numerica("rango_pct", "Rango / valor %", ",.0f"),
    {"field": "detalle", "headerName": "Detalle", "minWidth": 280, "flex": 3, "tooltipField": "detalle"},
    {"field": "fuente", "headerName": "Fuente (texto de la OMS)", "minWidth": 240, "flex": 3, "tooltipField": "fuente"},
]


def ficha_html(fila):
    """Lo que hay que saber del indicador antes de leer las gráficas."""
    def si(condicion, elemento):
        return [elemento] if condicion else []
    datos_ficha = (
        si(pd.notna(fila.unidad), html.Li(["Unidad: ", html.Strong(fila.unidad)]))
        + [html.Li(["Tipo: ", html.Strong(TIPOS.get(fila.tipo_dato, "sin ficha detallada"))])]
        + si(pd.notna(fila.organizacion), html.Li(["Lo produce: ", fila.organizacion]))
        + [html.Li(f"Cobertura: {fila.observaciones:,} datos de {fila.ubicaciones} lugares, "
                   f"{fila.anio_desde}–{fila.anio_hasta}")]
        + si(pd.notna(fila.ultima_publicacion_oms),
             html.Li(f"Última publicación de la OMS: {fecha(fila.ultima_publicacion_oms, '%Y-%m-%d')}"))
        + si(pd.notna(fila.meta), html.Li(f"Meta ODS 3.1: menos de {fila.meta:g} en el mundo para 2030"))
        + si(pd.notna(fila.url_metodologia), html.Li(html.A(
            "Definición completa y metodología (OMS)", href=fila.url_metodologia, target="_blank", rel="noopener"))))
    return ([html.Div(className="ficha-titulo", children=[html.Strong(fila.nombre),
                                                           html.Span(f"  {fila.codigo}", className="tenue")])]
            + si(pd.notna(fila.definicion), html.P(fila.definicion))
            + [html.Ul(className="ficha-datos", children=datos_ficha)])


# Página

app = Dash(__name__, title="Monitor de mortalidad materna")
server = app.server
# Botones de las gráficas. Las formas de los países salen de assets/mapa/ y no de internet,
# así el mapa también funciona sin conexión.
CONFIG = {"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d", "autoScale2d"],
          "toImageButtonOptions": {"format": "png", "scale": 2}, "topojsonURL": app.get_asset_url("mapa/")}

app.layout = html.Div(className="pagina", children=[
    dcc.Interval(id="reloj", interval=30_000),
    dcc.Store(id="version"),
    dcc.Store(id="colores", data={codigo: i for i, codigo in enumerate(LUGARES_INICIALES)}),
    html.Header(className="encabezado", children=[
        html.H1("Monitor mundial de mortalidad materna (ODS 3.1)"),
        html.P(id="estado-carga", className="subtitulo", children="Conectando con la base de datos…"),
        html.P(className="cita", children=[
            "Fuente: Organización Mundial de la Salud (OMS), ",
            html.A("Global Health Observatory", href="https://www.who.int/data/gho", target="_blank", rel="noopener"),
            ", consultado con su API. Los valores y los nombres se muestran tal como los publica la OMS."]),
    ]),
    html.Div(id="aviso", className="aviso", role="alert", hidden=True),
    html.Section(className="filtros", children=[
        campo("Indicador", dcc.Dropdown(id="indicador", value=INDICADOR_INICIAL, clearable=False, labels=LISTA), "campo-ancho"),
        # Las opciones iniciales evitan que la lista borre la selección antes de que lleguen los datos.
        campo(f"Países y regiones (hasta {MAXIMO_LUGARES})",
              dcc.Dropdown(id="ubicaciones", value=LUGARES_INICIALES, multi=True, labels=LISTA,
                           options=[{"label": "Mexico", "value": "MEX"}, {"label": "Región: Americas", "value": "AMR"},
                                    {"label": "Mundo: Global", "value": "GLOBAL"}]), "campo-ancho"),
        campo("Años", dcc.RangeSlider(id="anios", min=1985, max=2025, step=1, value=[1985, 2025], marks={},
                                      allowCross=False), "campo-anios"),
        campo("Cambio importante desde", html.Div(className="umbral", children=[
            dcc.Input(id="umbral", type="number", min=1, max=1000, step=1, value=25, debounce=True),
            html.Span("%")])),
    ]),
    html.Section(id="ficha", className="ficha"),
    dcc.Tabs(id="pestanas", value="tendencia", className="pestanas", content_className="pestanas-contenido",
             children=[
        dcc.Tab(label="Tendencia", value="tendencia", style=PESTANA, selected_style=PESTANA_ACTIVA, children=[
            html.P(id="nota-tendencia", className="nota"),
            dcc.Graph(id="grafica-tendencia", config=CONFIG)]),
        dcc.Tab(label="Mapa", value="mapa", style=PESTANA, selected_style=PESTANA_ACTIVA, children=[
            html.P(id="nota-mapa", className="nota"),
            dcc.Graph(id="grafica-mapa", config=CONFIG)]),
        dcc.Tab(label="Relación entre indicadores", value="relacion", style=PESTANA, selected_style=PESTANA_ACTIVA,
                children=[
            html.Div(className="fila-control", children=[
                campo("Comparar con", dcc.Dropdown(id="indicador-y", clearable=False, labels=LISTA), "campo-ancho")]),
            html.P(id="nota-relacion", className="nota"),
            dcc.Graph(id="grafica-relacion", config=CONFIG)]),
        dcc.Tab(label="Cambios importantes", value="cambios", style=PESTANA, selected_style=PESTANA_ACTIVA,
                children=[
            html.P(id="nota-cambios", className="nota"),
            tabla("tabla-cambios", COLUMNAS_CAMBIOS)]),
        dcc.Tab(label="Datos", value="datos", style=PESTANA, selected_style=PESTANA_ACTIVA, children=[
            html.Div(className="fila-control", children=[
                dcc.Checklist(id="todas", className="casilla", value=[],
                              options=[{"label": " Incluir todos los países y regiones", "value": "todas"}]),
                html.Button("Descargar CSV", id="descargar", className="boton")]),
            html.P(id="nota-datos", className="nota"),
            tabla("tabla-datos", COLUMNAS_DATOS)]),
    ]),
    html.Footer(className="notas", children=[html.H2("Cómo leer estos datos"),
                                             html.Ul([html.Li(nota) for nota in NOTAS])]),
])


# Cada 30 segundos: ¿la base responde?, ¿hay datos nuevos?

@callback(Output("version", "data"), Output("estado-carga", "children"),
          Output("aviso", "children"), Output("aviso", "hidden"),
          Input("reloj", "n_intervals"), State("version", "data"))
def revisar_base(_, version_actual):
    try:
        version, ultima_ok = datos.estado()
    except Exception as error:
        log.warning("La base no responde: %s", error)
        return no_update, no_update, "No pude conectar con la base de datos. Vuelvo a intentar en 30 segundos.", False
    if ultima_ok is None or pd.isna(ultima_ok):
        texto = "Todavía no hay datos: el recolector no ha terminado su primera carga."
    else:
        texto = f"Última carga de datos: {fecha(ultima_ok)}. Se revisa cada 30 segundos si hay datos nuevos."
    return (no_update if version == version_actual else version), texto, "", True


@callback(Output("indicador", "options"), Output("indicador", "value"),
          Output("indicador-y", "options"), Output("indicador-y", "value"),
          Input("version", "data"), State("indicador", "value"), State("indicador-y", "value"),
          prevent_initial_call=True)
@seguro(no_update, no_update, no_update, no_update)
def opciones_indicadores(version, actual, actual_y):
    tabla_ind = datos.indicadores(version)
    opciones = [{"label": f"{f.nombre}  ({f.codigo})", "value": f.codigo} for f in tabla_ind.itertuples()]
    codigos = list(tabla_ind.codigo)
    if actual in codigos:
        valor = no_update
        elegido = actual
    else:
        elegido = INDICADOR_INICIAL if INDICADOR_INICIAL in codigos else (codigos[0] if codigos else None)
        valor = elegido
    if actual_y in codigos and actual_y != elegido:
        valor_y = no_update
    else:
        valor_y = next((c for c in ["MDG_0000000025", INDICADOR_INICIAL, *codigos]
                        if c in codigos and c != elegido), None)
    return opciones, valor, opciones, valor_y


@callback(Output("ubicaciones", "options"), Output("anios", "min"), Output("anios", "max"),
          Output("anios", "value"), Output("anios", "marks"), Output("ficha", "children"),
          Input("indicador", "value"), Input("version", "data"),
          State("ubicaciones", "value"), State("anios", "value"),
          prevent_initial_call=True)
@seguro(no_update, no_update, no_update, no_update, no_update, no_update)
def controles_del_indicador(indicador, version, seleccion, anios):
    serie = datos.series(version, indicador)
    nombres = nombres_de(version)
    # Primero el mundo y las regiones, luego los países.
    tipos = serie.groupby("ubicacion_codigo").ubicacion_tipo.first()
    orden = {"GLOBAL": 0, "REGION": 1}
    codigos = sorted(tipos.index, key=lambda c: (orden.get(tipos[c], 2), nombres.get(c, c)))
    prefijo = {"GLOBAL": "Mundo: ", "REGION": "Región: "}
    opciones = [{"label": prefijo.get(tipos[c], "") + nombres.get(c, c), "value": c} for c in codigos]
    # Los lugares elegidos que no tienen dato se quedan en la lista; si no, la lista los quitaría.
    for c in seleccion or []:
        if c not in tipos.index:
            opciones.append({"label": f"{nombres.get(c, c)} (sin dato en este indicador)", "value": c})
    if serie.empty:
        return opciones, 1985, 2025, [1985, 2025], {}, [html.P("Este indicador todavía no tiene datos.")]
    minimo, maximo = int(serie.anio.min()), int(serie.anio.max())
    if ctx.triggered_id == "indicador" or not anios:
        valor = [minimo, maximo]
    else:
        valor = [max(minimo, min(anios[0], maximo)), max(minimo, min(anios[1], maximo))]
    ficha = ficha_de(version, indicador)
    return opciones, minimo, maximo, valor, {}, ([] if ficha is None else ficha_html(ficha))


@callback(Output("colores", "data"), Input("ubicaciones", "value"), State("colores", "data"))
def asignar_colores(seleccion, colores):
    """Cada lugar conserva su color aunque se quiten otros (el color sigue al lugar, no a su posición)."""
    seleccion = (seleccion or [])[:MAXIMO_LUGARES]
    colores = {c: i for c, i in (colores or {}).items() if c in seleccion}
    libres = [i for i in range(len(graficas.SERIES)) if i not in colores.values()]
    for codigo in seleccion:
        if codigo not in colores and libres:
            colores[codigo] = libres.pop(0)
    return colores


# Pestañas

@callback(Output("grafica-tendencia", "figure"), Output("nota-tendencia", "children"),
          Input("indicador", "value"), Input("ubicaciones", "value"), Input("anios", "value"),
          Input("colores", "data"), Input("version", "data"), prevent_initial_call=True)
@seguro(graficas.vacia(FALLA), "")
def pestana_tendencia(indicador, seleccion, anios, colores, version):
    serie = recorte(version, indicador, anios)
    ficha = ficha_de(version, indicador)
    elegidos = (seleccion or [])[:MAXIMO_LUGARES]
    fig = graficas.tendencia(serie, elegidos, colores or {},
                             None if ficha is None else ficha.meta, None if ficha is None else ficha.unidad)
    nombres = nombres_de(version)
    con_dato = set(serie.ubicacion_codigo)
    notas = []
    sin = [nombres.get(c, c) for c in elegidos if c not in con_dato]
    if sin:
        if not datos.series(version, indicador).ubicacion_tipo.ne("COUNTRY").any():
            notas.append("Este indicador solo trae países: la OMS no publica un valor de región ni del mundo, "
                         f"y aquí no se calcula un promedio. Sin dato: {', '.join(sin)}.")
        else:
            notas.append(f"Sin dato en estos años para: {', '.join(sin)}.")
    if len(seleccion or []) > MAXIMO_LUGARES:
        notas.append(f"Se muestran solo los primeros {MAXIMO_LUGARES} lugares.")
    # Las notas explican lo que de verdad aparece en la gráfica.
    vistos = serie[serie.ubicacion_codigo.isin(elegidos)]
    if vistos.valor_min.notna().any():
        notas.append("La banda alrededor de cada línea es el rango de incertidumbre: si las bandas se enciman, "
                     "no se puede decir que un lugar esté peor que otro.")
    if (vistos.cambio_fuente == 1).any():
        notas.append("Los círculos marcan los años en que la fuente cambió (o cambió cómo está escrita). "
                     "Un cambio de fuente puede parecer una tendencia.")
    return fig, " ".join(notas)


@callback(Output("grafica-mapa", "figure"), Output("nota-mapa", "children"),
          Input("indicador", "value"), Input("anios", "value"), Input("version", "data"),
          prevent_initial_call=True)
@seguro(graficas.vacia(FALLA), "")
def pestana_mapa(indicador, anios, version):
    serie = recorte(version, indicador, anios)
    ultimos = serie.sort_values("anio").groupby("ubicacion_codigo").tail(1)
    paises = ultimos[ultimos.ubicacion_tipo == "COUNTRY"]
    ficha = ficha_de(version, indicador)
    fig = graficas.mapa(paises, None if ficha is None else ficha.unidad)
    if paises.empty:
        return fig, ""
    desde, hasta = int(paises.anio.min()), int(paises.anio.max())
    cuando = f"todos son de {hasta}" if desde == hasta else f"van de {desde} a {hasta}"
    notas = [f"{len(paises)} países, cada uno con su dato más reciente dentro de los años elegidos ({cuando}; "
             "el año de cada país sale al pasar el cursor). Para ver un solo año, deja el rango de años en ese año.",
             "Más oscuro es un valor más alto; gris es sin dato."]
    if graficas.usa_logaritmo(paises.valor):
        notas.append("Los colores van en escala logarítmica para que también se distingan los países con valores "
                     "bajos: cada marca de la barra vale unas tres veces la anterior.")
    fuera = int((~paises.ubicacion_codigo.isin(graficas.EN_EL_MAPA)).sum())
    if fuera:
        notas.append(f"{fuera} países son muy pequeños para este mapa y no se ven; están en la pestaña Datos.")
    notas.append("Las fronteras son solo de referencia (formas de plotly.js hechas con datos de la ONU).")
    return fig, " ".join(notas)


@callback(Output("grafica-relacion", "figure"), Output("nota-relacion", "children"),
          Input("indicador", "value"), Input("indicador-y", "value"), Input("ubicaciones", "value"),
          Input("anios", "value"), Input("version", "data"), prevent_initial_call=True)
@seguro(graficas.vacia(FALLA), "")
def pestana_relacion(indicador, indicador_y, seleccion, anios, version):
    if not indicador_y or indicador_y == indicador:
        return graficas.vacia("Elige en «Comparar con» un indicador distinto."), ""
    ficha_x, ficha_y = ficha_de(version, indicador), ficha_de(version, indicador_y)
    fig, pares = graficas.relacion(recorte(version, indicador, anios), recorte(version, indicador_y, anios),
                                   ficha_x.nombre, ficha_y.nombre, seleccion or [])
    if pares.empty:
        return fig, ""
    nota = (f"{len(pares)} países con dato de los dos indicadores en el mismo año. Cada punto usa el año más "
            "reciente en que el país tiene los dos (está en el detalle). Los lugares elegidos arriba van en naranja. "
            "Que dos indicadores se muevan juntos no quiere decir que uno cause el otro.")
    return fig, nota


@callback(Output("tabla-cambios", "rowData"), Output("nota-cambios", "children"),
          Input("indicador", "value"), Input("anios", "value"), Input("umbral", "value"),
          Input("version", "data"), prevent_initial_call=True)
@seguro([], FALLA)
def pestana_cambios(indicador, anios, umbral, version):
    """Junta los cambios grandes respecto al dato anterior. No dice si están bien o mal: eso lo decide quien revisa."""
    serie = recorte(version, indicador, anios)
    umbral = umbral if umbral and umbral > 0 else 25
    cambios = serie[serie.cambio_pct.abs() >= umbral].copy()
    detalles, antes = [], []
    for f in cambios.itertuples():
        # La fuente y el rango no hacen que un dato aparezca aquí, pero ayudan a leer el cambio.
        partes = [f"cambio de {f.cambio_pct:+.0f}% desde {int(f.anio_anterior)}"]
        if f.cambio_fuente == 1:
            partes.append("la fuente cambió (o cambió cómo está escrita)")
        if pd.notna(f.ancho_rango_relativo) and f.ancho_rango_relativo >= RANGO_ANCHO:
            partes.append("rango de incertidumbre más ancho que el valor")
        detalles.append("; ".join(partes))
        antes.append(f"{int(f.anio_anterior)}: {graficas.numero(f.valor_anterior)}")
    cambios["detalle"] = detalles
    cambios["antes"] = antes
    cambios["rango_pct"] = cambios.ancho_rango_relativo * 100
    cambios["orden"] = cambios.cambio_pct.abs()
    cambios = cambios.sort_values(["orden", "anio"], ascending=[False, False])
    columnas = ["ubicacion_nombre", "ubicacion_tipo", "anio", "valor", "antes", "cambio_pct", "rango_pct",
                "detalle", "fuente"]
    nota = f"{len(cambios):,} cambios de {umbral:g}% o más respecto al dato anterior"
    con_fuente = int((cambios.cambio_fuente == 1).sum())
    if con_fuente:
        nota += f"; en {con_fuente:,} de ellos también cambió la fuente, y eso puede explicar el salto"
    nota += (". Se buscan en todos los países y regiones, dentro de los años elegidos. La columna «Rango / valor %» "
             "ayuda a ver si un cambio cabe dentro de la incertidumbre. Que un dato aparezca aquí no quiere decir que "
             "esté mal: cada quien lo revisa con su contexto.")
    return filas(cambios[columnas]), nota


@callback(Output("tabla-datos", "rowData"), Output("nota-datos", "children"),
          Input("indicador", "value"), Input("ubicaciones", "value"), Input("anios", "value"),
          Input("todas", "value"), Input("version", "data"), prevent_initial_call=True)
@seguro([], FALLA)
def pestana_datos(indicador, seleccion, anios, todas, version):
    serie = recorte(version, indicador, anios)
    if not todas:
        serie = serie[serie.ubicacion_codigo.isin(seleccion or [])]
    columnas = ["indicador_codigo", "ubicacion_nombre", "ubicacion_codigo", "ubicacion_tipo", "anio", "periodo",
                "valor", "valor_min", "valor_max", "fuente", "fecha_publicacion_oms", "fecha_carga"]
    vista = serie[columnas].copy()
    for columna in ("fecha_publicacion_oms", "fecha_carga"):
        vista[columna] = vista[columna].map(lambda v: fecha(v, "%Y-%m-%d %H:%M:%S"))
    nota = (f"{len(vista):,} filas. «Descargar CSV» baja lo que se ve en la tabla, con los filtros de cada columna, "
            "y con los valores completos (sin redondear). Cita a la OMS como fuente al usarlos.")
    return filas(vista), nota


@callback(Output("tabla-datos", "exportDataAsCsv"), Output("tabla-datos", "csvExportParams"),
          Input("descargar", "n_clicks"), State("indicador", "value"), prevent_initial_call=True)
def descargar(_, indicador):
    hoy = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return True, {"fileName": f"oms_{indicador}_{hoy}.csv"}


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8050, debug=False)
