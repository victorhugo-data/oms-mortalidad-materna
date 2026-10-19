"""Consultas a la API GHO de la OMS: https://www.who.int/data/gho/info/gho-odata-api"""
import json
import logging
from urllib.parse import quote

import requests

from salud import esperar, latido

log = logging.getLogger("recolector")

AGENTE = "oms-mortalidad-materna/1.0 (+https://github.com/victorhugo-data/oms-mortalidad-materna)"
TIEMPO_MAXIMO = (10, 120)          # segundos para conectar y para recibir la respuesta
ESPERAS = (10, 30, 60)             # tres reintentos, cada vez esperando más
REINTENTAR = {429, 500, 502, 503, 504}


class ErrorAPI(Exception):
    """La API no dio una respuesta que se pueda usar."""


def ruta_catalogo(dimension):
    """Regiones (REGION), países (COUNTRY) o total mundial (GLOBAL)."""
    return f"DIMENSION/{dimension}/DimensionValues"


def ruta_nombres(codigos):
    """El catálogo de indicadores, solo con los que usamos."""
    filtro = " or ".join(f"IndicatorCode eq '{codigo}'" for codigo in codigos)
    return "Indicator?$filter=" + quote(filtro, safe="'")


def leer_json(url, contenido):
    """Regresa (texto, registros). El texto se guarda en crudo exactamente como llegó."""
    try:
        texto = contenido.decode("utf-8")
        datos = json.loads(texto)
    except ValueError:
        raise ErrorAPI(f"{url} no regresó un JSON válido") from None
    if not isinstance(datos, dict) or not isinstance(datos.get("value"), list):
        raise ErrorAPI(f"{url} no trae la lista 'value'")
    if "@odata.nextLink" in datos:
        raise ErrorAPI(f"{url} vino partida en páginas y el recolector todavía no las junta")
    return texto, datos["value"]


class ClienteOMS:
    def __init__(self, base):
        self.base = base.rstrip("/")
        self.sesion = requests.Session()
        self.sesion.headers["User-Agent"] = AGENTE

    def url(self, ruta):
        return f"{self.base}/{ruta}"

    def pedir(self, ruta):
        """Pide una ruta a la API y regresa (texto, registros). Si la red falla, reintenta."""
        url = self.url(ruta)
        for intento in range(len(ESPERAS) + 1):
            latido()
            try:
                respuesta = self.sesion.get(url, timeout=TIEMPO_MAXIMO)
            except requests.RequestException as error:
                problema = f"sin respuesta ({error.__class__.__name__})"
            else:
                if respuesta.status_code == 200:
                    return leer_json(url, respuesta.content)
                if respuesta.status_code not in REINTENTAR:
                    raise ErrorAPI(f"{url} respondió {respuesta.status_code}")
                problema = f"respondió {respuesta.status_code}"
            if intento == len(ESPERAS):
                raise ErrorAPI(f"{url}: {problema}, después de {intento + 1} intentos")
            log.warning("%s: %s; reintento en %s s", url, problema, ESPERAS[intento])
            esperar(ESPERAS[intento])

    def nombres_indicadores(self, codigos):
        """{código: nombre oficial} según el catálogo de indicadores de la OMS."""
        _, registros = self.pedir(ruta_nombres(codigos))
        return {r.get("IndicatorCode"): r.get("IndicatorName") for r in registros if isinstance(r, dict)}
