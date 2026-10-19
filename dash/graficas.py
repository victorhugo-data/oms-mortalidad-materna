"""Las gráficas del dashboard. Un solo eje por gráfica y colores aptos para daltonismo."""
import json
import os

import numpy as np
import pandas as pd
import plotly.graph_objects as go

# Colores por identidad, siempre en este orden: el color sigue al lugar, no a su posición.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
# Un solo tono de claro a oscuro para magnitudes (el mapa): más oscuro es un valor más alto.
SECUENCIAL = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#2a78d6", "#1c5cab", "#104281", "#0d366b"]
SUPERFICIE, TINTA, TINTA_2, TENUE = "#fcfcfb", "#0b0b0b", "#52514e", "#898781"
REJILLA, EJE, SIN_DATO = "#e1e0d9", "#c3c2b7", "#e8e7e2"
LETRA = 'system-ui, -apple-system, "Segoe UI", sans-serif'

# Los países que trae el archivo del mapa. Los muy pequeños (San Marino, Malta, varias islas) no vienen.
with open(os.path.join(os.path.dirname(__file__), "assets", "mapa", "world_110m.json"), encoding="utf-8") as archivo:
    EN_EL_MAPA = {g["id"] for g in json.load(archivo)["objects"]["countries"]["geometries"] if g.get("id")}


def rgba(color, opacidad):
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r},{g},{b},{opacidad})"


def numero(valor, decimales=1):
    """103.877921 -> '103.9'. Vacío si no hay valor."""
    return "" if pd.isna(valor) else f"{valor:,.{decimales}f}"


def rango(minimo, maximo):
    return "" if pd.isna(minimo) or pd.isna(maximo) else f"rango {numero(minimo)}–{numero(maximo)}"


def corto(texto, largo=90):
    """Para los cuadritos de detalle: la fuente en una línea y recortada (la tabla trae el texto completo)."""
    if texto is None or pd.isna(texto):
        return ""
    texto = " ".join(str(texto).split())
    return texto if len(texto) <= largo else texto[:largo - 1] + "…"


def nombre_lugar(fila):
    return fila.ubicacion_nombre if pd.notna(fila.ubicacion_nombre) else fila.ubicacion_codigo


def periodo(fila):
    return fila.periodo if pd.notna(fila.periodo) else str(fila.anio)


def periodo_y_fuente(fila, largo=90):
    """'Periodo 2013-2015 · texto de la fuente', o solo el periodo si la OMS no da fuente."""
    fuente = corto(fila.fuente, largo)
    return f"Periodo {periodo(fila)}" + (f" · {fuente}" if fuente else "")


def base(fig, alto=460, derecha=24):
    fig.update_layout(
        template="none", height=alto, paper_bgcolor=SUPERFICIE, plot_bgcolor=SUPERFICIE,
        font=dict(family=LETRA, size=13, color=TINTA_2),
        margin=dict(l=64, r=derecha, t=24, b=56),
        hoverlabel=dict(bgcolor="#ffffff", bordercolor=EJE, font=dict(family=LETRA, size=13, color=TINTA)),
        legend=dict(orientation="h", x=0, y=-0.18, font=dict(color=TINTA_2)),
    )
    fig.update_xaxes(showgrid=False, showline=True, linecolor=EJE, ticks="outside", tickcolor=EJE,
                     tickfont=dict(color=TENUE), title_font=dict(color=TINTA_2), zeroline=False)
    fig.update_yaxes(showgrid=True, gridcolor=REJILLA, gridwidth=1, zeroline=False, rangemode="tozero",
                     tickfont=dict(color=TENUE), title_font=dict(color=TINTA_2))
    return fig


def vacia(mensaje):
    """Una gráfica sin datos, con un mensaje al centro."""
    fig = base(go.Figure(), alto=320)
    fig.add_annotation(text=mensaje, showarrow=False, x=0.5, y=0.5, xref="paper", yref="paper",
                       font=dict(color=TINTA_2, size=14))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return fig


def tendencia(datos, seleccion, colores, meta, unidad):
    """Una línea por lugar, con su banda de incertidumbre y la meta si el indicador la tiene."""
    fig = go.Figure()
    con_dato = [c for c in seleccion if c in set(datos.ubicacion_codigo)]
    if not con_dato:
        return vacia("No hay datos de los lugares elegidos en estos años.")
    leyenda_fuente = False
    finales = []   # (nombre, último año, último valor) de cada línea
    for codigo in con_dato:
        d = datos[datos.ubicacion_codigo == codigo].sort_values("anio")
        color = SERIES[colores.get(codigo, 0) % len(SERIES)]
        nombre = nombre_lugar(d.iloc[0])
        finales.append((nombre, d.anio.iloc[-1], float(d.valor.iloc[-1])))
        if d.valor_min.notna().all() and d.valor_max.notna().all():
            fig.add_trace(go.Scatter(
                x=list(d.anio) + list(d.anio[::-1]), y=list(d.valor_max) + list(d.valor_min[::-1]),
                fill="toself", fillcolor=rgba(color, 0.12), line=dict(width=0),
                hoverinfo="skip", showlegend=False, legendgroup=codigo))
        detalle = [[rango(f.valor_min, f.valor_max), periodo_y_fuente(f)] for f in d.itertuples()]
        fig.add_trace(go.Scatter(
            x=d.anio, y=d.valor, name=nombre, legendgroup=codigo, mode="lines+markers",
            line=dict(color=color, width=2), marker=dict(size=8, color=color, line=dict(color=SUPERFICIE, width=2)),
            customdata=detalle,
            hovertemplate="<b>%{y:,.1f}</b>  %{customdata[0]}<br>%{customdata[1]}<extra>%{fullData.name}</extra>"))
        cambios = d[d.cambio_fuente == 1]
        if not cambios.empty:
            fig.add_trace(go.Scatter(
                x=cambios.anio, y=cambios.valor, mode="markers", name="La fuente cambió",
                legendgroup="fuente", showlegend=not leyenda_fuente, hoverinfo="skip",
                marker=dict(symbol="circle-open", size=15, color=TINTA_2, line=dict(width=1.5))))
            leyenda_fuente = True
    vistos = datos[datos.ubicacion_codigo.isin(con_dato)]
    tope = pd.concat([vistos.valor, vistos.valor_max]).max()
    if meta is not None and pd.notna(meta):
        # La meta va como una línea punteada con su nombre en la leyenda (así no tapa los datos).
        fig.add_trace(go.Scatter(
            x=[vistos.anio.min(), vistos.anio.max()], y=[meta, meta], mode="lines", hoverinfo="skip",
            name=f"Meta mundial ODS 2030: menos de {meta:g}", line=dict(color=TINTA_2, width=1, dash="dash")))
        tope = max(tope, float(meta))
    # El nombre al final de cada línea, solo si son pocas y todas terminan el mismo año; si no,
    # los nombres se enciman con otras líneas (la leyenda siempre está). Si dos nombres quedan
    # muy juntos, el de abajo se recorre un poco (5 % del alto, unos 16 píxeles).
    con_nombres = len(finales) <= 4 and len({anio for _, anio, _ in finales}) == 1
    if con_nombres:
        altura = None
        for nombre, anio, valor in sorted(finales, key=lambda f: -f[2]):
            altura = valor if altura is None else min(valor, altura - 0.05 * float(tope))
            fig.add_annotation(x=anio, y=altura, text=nombre[:22], showarrow=False,
                               xanchor="left", xshift=10, font=dict(color=TINTA_2, size=12))
    base(fig, derecha=150 if con_nombres else 24)
    fig.update_layout(hovermode="x unified")
    fig.update_xaxes(title_text="Año", dtick=5)
    fig.update_yaxes(title_text=unidad or "")
    return fig


def usa_logaritmo(valores):
    """True si los valores van de muy bajos a muy altos (como la mortalidad materna, de 1 a casi 1,000).

    Con una escala normal, casi todos los países saldrían del mismo tono claro.
    """
    valores = valores.astype(float)
    return len(valores) >= 10 and valores.min() > 0 and valores.quantile(0.9) / valores.quantile(0.1) >= 20


def mapa(datos, unidad):
    """Mapa de países: más oscuro es un valor más alto; gris es sin dato."""
    paises = datos[datos.ubicacion_tipo == "COUNTRY"]
    if paises.empty:
        return vacia("No hay datos de países para este año.")
    detalle = [[nombre_lugar(f), numero(f.valor), rango(f.valor_min, f.valor_max), periodo_y_fuente(f, 70)]
               for f in paises.itertuples()]
    escala = [[i / (len(SECUENCIAL) - 1), c] for i, c in enumerate(SECUENCIAL)]
    barra = dict(title=dict(text=unidad or "", side="right", font=dict(color=TINTA_2)), thickness=12,
                 len=0.7, outlinewidth=0, tickfont=dict(color=TENUE))
    valores = paises.valor.astype(float)
    if usa_logaritmo(valores):
        # El color sigue al logaritmo del valor; la barra muestra los valores reales.
        z = np.log10(valores)
        bajo, alto = valores.quantile(0.05), valores.max()
        marcas = [m for m in (0.1, 0.3, 1, 3, 10, 30, 100, 300, 1000, 3000, 10000) if bajo <= m <= alto]
        barra.update(tickvals=np.log10(marcas), ticktext=[f"{m:,g}" for m in marcas])
        limites = dict(zmin=np.log10(bajo), zmax=np.log10(alto))
    else:
        z, limites = valores, {}
    fig = go.Figure(go.Choropleth(
        locations=paises.ubicacion_codigo, z=z, locationmode="ISO-3", colorscale=escala, **limites,
        marker=dict(line=dict(color=SUPERFICIE, width=0.5)), customdata=detalle, colorbar=barra,
        hovertemplate="<b>%{customdata[0]}</b><br><b>%{customdata[1]}</b>  %{customdata[2]}"
                      "<br>%{customdata[3]}<extra></extra>"))
    fig.update_geos(projection_type="natural earth", showframe=False, showcoastlines=False, showland=True,
                    landcolor=SIN_DATO, showcountries=True, countrycolor=SUPERFICIE, showocean=False,
                    bgcolor=SUPERFICIE, lataxis_range=[-58, 85])
    base(fig, alto=520)
    fig.update_layout(margin=dict(l=0, r=0, t=8, b=8))
    return fig


def relacion(x, y, nombre_x, nombre_y, seleccion):
    """Un punto por país, con el año más reciente en que tiene dato de los dos indicadores."""
    a = x[x.ubicacion_tipo == "COUNTRY"][["ubicacion_codigo", "ubicacion_nombre", "anio", "valor"]]
    b = y[y.ubicacion_tipo == "COUNTRY"][["ubicacion_codigo", "anio", "valor"]]
    pares = a.merge(b, on=["ubicacion_codigo", "anio"], suffixes=("_x", "_y"))
    if pares.empty:
        return vacia("Estos dos indicadores no tienen ningún país con dato en el mismo año."), pares
    pares = pares.sort_values("anio").groupby("ubicacion_codigo").tail(1)
    plantilla = ("<b>%{customdata[0]}</b> · " + "%{customdata[1]}<br>" + nombre_x[:45] + ": <b>%{x:,.1f}</b><br>"
                 + nombre_y[:45] + ": <b>%{y:,.1f}</b><extra></extra>")
    fig = go.Figure()
    resto = pares[~pares.ubicacion_codigo.isin(seleccion)]
    fig.add_trace(go.Scatter(
        x=resto.valor_x, y=resto.valor_y, mode="markers", name="Países",
        marker=dict(size=9, color=rgba(SERIES[0], 0.55), line=dict(color=SUPERFICIE, width=1)),
        customdata=resto[["ubicacion_nombre", "anio"]].values.tolist(), hovertemplate=plantilla))
    elegidos = pares[pares.ubicacion_codigo.isin(seleccion)]
    if not elegidos.empty:
        fig.add_trace(go.Scatter(
            x=elegidos.valor_x, y=elegidos.valor_y, mode="markers+text", name="Elegidos arriba",
            text=elegidos.ubicacion_nombre, textposition="top center", textfont=dict(color=TINTA, size=12),
            marker=dict(size=12, color=SERIES[1], line=dict(color=SUPERFICIE, width=2)),
            customdata=elegidos[["ubicacion_nombre", "anio"]].values.tolist(), hovertemplate=plantilla))
    base(fig)
    fig.update_layout(hovermode="closest", hoverdistance=20)
    fig.update_xaxes(title_text=nombre_x, showgrid=True, gridcolor=REJILLA, rangemode="tozero")
    fig.update_yaxes(title_text=nombre_y)
    return fig, pares
