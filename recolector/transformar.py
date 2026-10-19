"""Revisa y convierte los registros de la API. Nunca cambia un valor de la OMS:
lo que no pasa las reglas se omite (y sigue guardado en crudo)."""
import math
import re
from datetime import datetime, timezone

# Mismas reglas y tamaños que las tablas de mysql/init/02_tablas.sql.
ANIO_MIN, ANIO_MAX = 1900, 2100
LARGO_CODIGO = 20
LARGO_TIPO = 30
LARGO_NOMBRE = 200
LARGO_PERIODO = 50
LARGO_DESAGREGACION = 255
CODIGO_INDICADOR = re.compile(r"^[A-Za-z0-9_]{1,50}$")

# Lo que se compara para saber si un dato cambió (lo mismo que revisa el trigger del historial).
CAMPOS = ("periodo", "valor", "valor_min", "valor_max", "fuente", "fecha_publicacion_oms")


class Omitido(Exception):
    """Un registro que no pasa las reglas. El mensaje es el motivo."""


def leer_indicadores(texto):
    """'A, B,,A' -> ['A', 'B']: quita espacios, vacíos y repetidos."""
    codigos = []
    for codigo in texto.split(","):
        codigo = codigo.strip()
        if not codigo:
            continue
        if not CODIGO_INDICADOR.match(codigo):
            raise ValueError(f"código de indicador no válido: {codigo!r}")
        if codigo not in codigos:
            codigos.append(codigo)
    return codigos


def es_numero(valor):
    return isinstance(valor, (int, float)) and not isinstance(valor, bool) and math.isfinite(valor)


def es_texto(valor, largo):
    return isinstance(valor, str) and 0 < len(valor) <= largo


def fecha_utc(texto):
    """'2025-04-10T15:44:11.957+02:00' -> 2025-04-10 13:44:11.957 (UTC, sin zona).
    Se queda en milisegundos, que es lo que guarda la base."""
    fecha = datetime.fromisoformat(texto)
    if fecha.tzinfo is None:
        raise ValueError("la fecha no trae zona horaria")
    fecha = fecha.astimezone(timezone.utc).replace(tzinfo=None)
    return fecha.replace(microsecond=fecha.microsecond // 1000 * 1000)


def desagregacion(registro):
    """'TOTAL' si no hay Dim1-Dim3; si hay, pares 'Tipo:valor' unidos con '|'."""
    partes = [f"{registro.get(f'Dim{i}Type') or ''}:{registro[f'Dim{i}']}"
              for i in (1, 2, 3) if registro.get(f"Dim{i}") is not None]
    return "|".join(partes) if partes else "TOTAL"


def fila_observacion(registro, codigo):
    """Convierte un registro de la API en una fila de limpio.observaciones.
    Regresa (llave, valores, tipo de ubicación). Si no pasa las reglas, lanza Omitido."""
    if registro.get("IndicatorCode") != codigo:
        raise Omitido("trae otro código de indicador")
    ubicacion, tipo = registro.get("SpatialDim"), registro.get("SpatialDimType")
    if not es_texto(ubicacion, LARGO_CODIGO) or not es_texto(tipo, LARGO_TIPO):
        raise Omitido("sin ubicación válida")
    anio = registro.get("TimeDim")
    if not isinstance(anio, int) or isinstance(anio, bool) or not ANIO_MIN <= anio <= ANIO_MAX:
        raise Omitido("año no válido")
    valor, minimo, maximo = registro.get("NumericValue"), registro.get("Low"), registro.get("High")
    if not es_numero(valor):
        raise Omitido("sin valor numérico")
    if any(x is not None and not es_numero(x) for x in (minimo, maximo)):
        raise Omitido("rango no numérico")
    valor = float(valor)
    minimo = None if minimo is None else float(minimo)
    maximo = None if maximo is None else float(maximo)
    # La misma regla que ck_observaciones_rango en la base.
    if (minimo is not None and minimo > valor) or (maximo is not None and valor > maximo):
        raise Omitido("valor fuera de su rango")
    grupo = desagregacion(registro)
    if len(grupo) > LARGO_DESAGREGACION:
        raise Omitido("desagregación demasiado larga")
    periodo = registro.get("TimeDimensionValue")
    if periodo is not None and not es_texto(periodo, LARGO_PERIODO):
        raise Omitido("periodo no válido")
    fuente = registro.get("Comments")
    if fuente is not None and not isinstance(fuente, str):
        raise Omitido("fuente no válida")
    fecha = registro.get("Date")
    if fecha is not None:
        try:
            fecha = fecha_utc(fecha)
        except (TypeError, ValueError):
            raise Omitido("fecha de publicación no válida") from None
    valores = {"periodo": periodo, "valor": valor, "valor_min": minimo, "valor_max": maximo,
               "fuente": fuente, "fecha_publicacion_oms": fecha}
    return (ubicacion, grupo, anio), valores, tipo


def filas_observaciones(registros, codigo):
    """Revisa todos los registros de un indicador.
    Regresa ({llave: valores}, {ubicación: tipo}, [(motivo, registro omitido)])."""
    filas, tipos, omitidos = {}, {}, []
    for registro in registros:
        if not isinstance(registro, dict):
            omitidos.append(("registro sin formato", registro))
            continue
        try:
            llave, valores, tipo = fila_observacion(registro, codigo)
        except Omitido as motivo:
            omitidos.append((str(motivo), registro))
            continue
        if llave in filas:
            omitidos.append(("repetido en la respuesta", registro))
            continue
        filas[llave] = valores
        tipos.setdefault(llave[0], tipo)
    return filas, tipos, omitidos


def filas_ubicaciones(entradas, dimension):
    """Convierte un catálogo de la API (DimensionValues) en filas de limpio.ubicaciones.
    Regresa ({código: (tipo, nombre, región)}, [(motivo, entrada omitida)])."""
    filas, omitidos = {}, []
    for entrada in entradas:
        codigo = entrada.get("Code") if isinstance(entrada, dict) else None
        if not es_texto(codigo, LARGO_CODIGO):
            omitidos.append(("sin código válido", entrada))
            continue
        nombre = entrada.get("Title")
        if nombre is not None and not es_texto(nombre, LARGO_NOMBRE):
            omitidos.append(("nombre no válido", entrada))
            continue
        if codigo in filas:
            omitidos.append(("repetido en la respuesta", entrada))
            continue
        region = entrada.get("ParentCode") if entrada.get("ParentDimension") == "REGION" else None
        filas[codigo] = (dimension, nombre, region)
    return filas, omitidos


def comparar(nuevas, guardadas):
    """Separa lo nuevo de lo que cambió. Lo que sigue igual no se toca.
    nuevas y guardadas: {llave: valores}. Regresa ({llave: valores} nuevas, {llave: valores} cambiadas)."""
    nuevo = {llave: v for llave, v in nuevas.items() if llave not in guardadas}
    cambiado = {llave: v for llave, v in nuevas.items() if llave in guardadas and v != guardadas[llave]}
    return nuevo, cambiado
