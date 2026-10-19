"""Recolector: baja los datos de la OMS y los guarda en MySQL.

En cada ciclo:
  1. Baja los catálogos de regiones, países y total mundial (limpio.ubicaciones).
  2. Por cada indicador de INDICADORES: guarda la respuesta tal cual en crudo, revisa cada
     registro y en limpio agrega lo nuevo y actualiza solo lo que la OMS cambió.

Uso:
  python recolector.py            ciclo continuo, cada INTERVALO_HORAS
  python recolector.py --una-vez  un solo ciclo (para la demo)
"""
import argparse
import logging
import os
import signal
import sys
import time
from collections import Counter

import api_oms
import base
import transformar
from salud import esperar, latido

log = logging.getLogger("recolector")
CATALOGOS = ("REGION", "COUNTRY", "GLOBAL")   # en este orden: las regiones antes que los países
ESPERA_TURNO = 600                            # segundos que espera si otro recolector está cargando
REINTENTO_CICLO = 600                         # si un ciclo falla entero (p. ej. sin MySQL), reintenta en 10 min


def resumir(omitidos):
    """'valor fuera de su rango: 2, sin valor numérico: 1'"""
    cuenta = Counter(motivo for motivo, _ in omitidos)
    return ", ".join(f"{motivo}: {n}" for motivo, n in cuenta.most_common())


def describir(registro):
    """Para el log: 'MEX 2012' o lo que se alcance a leer del registro."""
    if not isinstance(registro, dict):
        return repr(registro)[:80]
    partes = [str(registro[c]) for c in ("SpatialDim", "TimeDim", "Dim1", "Code") if registro.get(c) is not None]
    return " ".join(partes) or "(registro vacío)"


def reportar_error(cx, carga_id, recibidos, nombre, error):
    log.error("%s: ERROR %s", nombre, error)
    try:
        base.marcar_error(cx, carga_id, recibidos, str(error))
    except Exception as otro:
        log.error("%s: tampoco pude anotar el error en la base (%s)", nombre, otro)


def cargar_catalogo(cx, cliente, dimension):
    ruta = api_oms.ruta_catalogo(dimension)
    carga_id = base.abrir_carga(cx, None, cliente.url(ruta))
    recibidos = 0
    try:
        texto, entradas = cliente.pedir(ruta)
        base.guardar_respuesta(cx, carga_id, texto)
        recibidos = len(entradas)
        filas, omitidos = transformar.filas_ubicaciones(entradas, dimension)
        guardadas = base.leer_ubicaciones(cx)
        # La región tiene que existir ya en la base (llave foránea); si no, se deja vacía.
        for codigo, (tipo, nombre, region) in filas.items():
            if region is not None and region not in guardadas:
                log.warning("Catálogo %s: la región %s de %s no está en la base; se deja vacía",
                            dimension, region, codigo)
                filas[codigo] = (tipo, nombre, None)
        nuevas, cambiadas = transformar.comparar(filas, guardadas)
        base.insertar_ubicaciones(cx, nuevas)
        base.actualizar_ubicaciones(cx, cambiadas)
        base.cerrar_carga(cx, carga_id, recibidos, len(nuevas), len(cambiadas), len(omitidos),
                          resumir(omitidos) or None)
        cx.commit()
    except Exception as error:
        reportar_error(cx, carga_id, recibidos, f"Catálogo {dimension}", error)
        return False
    log.info("Catálogo %s: recibidos %d, nuevos %d, cambiados %d, omitidos %d",
             dimension, recibidos, len(nuevas), len(cambiadas), len(omitidos))
    return True


def cargar_indicador(cx, cliente, codigo, nombres_oms):
    carga_id = base.abrir_carga(cx, codigo, cliente.url(codigo))
    recibidos = 0
    try:
        texto, registros = cliente.pedir(codigo)
        base.guardar_respuesta(cx, carga_id, texto)
        recibidos = len(registros)
        filas, tipos, omitidos = transformar.filas_observaciones(registros, codigo)

        # Ficha del indicador: si no existe se crea con el nombre de la OMS; si la OMS
        # le cambió el nombre, se actualiza.
        fichas = base.leer_nombres_indicadores(cx)
        nombre = nombres_oms.get(codigo)
        if codigo not in fichas:
            if not nombre:
                raise ValueError(f"{codigo} no aparece en el catálogo de indicadores de la OMS")
            base.crear_indicador(cx, codigo, nombre)
            log.info("%s: ficha nueva con el nombre de la OMS: %s", codigo, nombre)
        elif nombre and nombre != fichas[codigo]:
            base.renombrar_indicador(cx, codigo, nombre)
            log.warning("%s: la OMS cambió el nombre; ahora es: %s", codigo, nombre)

        # Ubicaciones que no vienen en los catálogos: se agregan con su código y su tipo.
        conocidas = base.leer_ubicaciones(cx)
        faltan = {u: (tipo, None, None) for u, tipo in tipos.items() if u not in conocidas}
        base.insertar_ubicaciones(cx, faltan)

        nuevas, cambiadas = transformar.comparar(filas, base.leer_observaciones(cx, codigo))
        base.insertar_observaciones(cx, codigo, carga_id, nuevas)
        base.actualizar_observaciones(cx, codigo, carga_id, cambiadas)
        base.cerrar_carga(cx, carga_id, recibidos, len(nuevas), len(cambiadas), len(omitidos),
                          resumir(omitidos) or None)
        cx.commit()
    except Exception as error:
        reportar_error(cx, carga_id, recibidos, codigo, error)
        return False

    log.info("%s: recibidos %d, nuevos %d, cambiados %d, omitidos %d",
             codigo, recibidos, len(nuevas), len(cambiadas), len(omitidos))
    if not registros:
        log.warning("%s: la API no regresó ningún dato", codigo)
    if faltan:
        log.info("%s: ubicaciones nuevas que no estaban en los catálogos: %s", codigo, ", ".join(sorted(faltan)))
    if omitidos:
        log.info("%s: motivos de los omitidos: %s", codigo, resumir(omitidos))
        for motivo, registro in omitidos[:5]:
            log.info("%s:   %s -> %s", codigo, describir(registro), motivo)
    return True


def ciclo(cliente, indicadores):
    """Una vuelta completa. Regresa True si todas las cargas salieron bien."""
    latido()
    cx = base.conectar()
    try:
        if not base.tomar_turno(cx, ESPERA_TURNO):
            log.warning("Otro recolector está cargando datos; esta vez no hago nada.")
            return False
        try:
            interrumpidas = base.cerrar_interrumpidas(cx)
            if interrumpidas:
                log.warning("%d carga(s) anteriores quedaron a medias; se marcaron como ERROR.", interrumpidas)
            todo_bien = True
            for dimension in CATALOGOS:
                if not cargar_catalogo(cx, cliente, dimension):
                    todo_bien = False
            try:
                nombres = cliente.nombres_indicadores(indicadores)
            except api_oms.ErrorAPI as error:
                log.warning("No pude leer los nombres de los indicadores (%s)", error)
                nombres = {}
            for codigo in indicadores:
                if not cargar_indicador(cx, cliente, codigo, nombres):
                    todo_bien = False
            return todo_bien
        finally:
            base.soltar_turno(cx)
    finally:
        cx.close()


def ciclo_seguro(cliente, indicadores):
    """Como ciclo(), pero si algo falla entero (p. ej. MySQL no responde) lo anota y regresa None."""
    inicio = time.monotonic()
    try:
        todo_bien = ciclo(cliente, indicadores)
    except Exception:
        log.exception("El ciclo falló")
        return None
    log.info("Ciclo terminado en %.0f s: %s", time.monotonic() - inicio,
             "todo bien" if todo_bien else "hubo errores (ver arriba)")
    return todo_bien


def detener(senal, _marco):
    log.info("Recibí la señal de apagado (%s); termino.", signal.Signals(senal).name)
    sys.exit(0)


def main():
    parser = argparse.ArgumentParser(description="Baja los datos de la OMS y los guarda en MySQL.")
    parser.add_argument("--una-vez", action="store_true", help="hace un solo ciclo y termina")
    argumentos = parser.parse_args()

    logging.Formatter.converter = time.gmtime
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s UTC %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    logging.getLogger("mysql.connector").setLevel(logging.WARNING)   # sin los avisos internos de la librería
    signal.signal(signal.SIGTERM, detener)

    try:
        indicadores = transformar.leer_indicadores(os.environ.get("INDICADORES", ""))
        horas = float(os.environ.get("INTERVALO_HORAS", "24"))
        if not indicadores:
            raise ValueError("INDICADORES está vacío")
        if horas <= 0:
            raise ValueError("INTERVALO_HORAS tiene que ser mayor que 0")
    except ValueError as error:
        log.error("Configuración no válida: %s", error)
        return 2

    cliente = api_oms.ClienteOMS(os.environ.get("API_BASE", "https://ghoapi.azureedge.net/api"))
    log.info("Recolector listo. Indicadores: %s.", ", ".join(indicadores))

    if argumentos.una_vez:
        return 0 if ciclo_seguro(cliente, indicadores) else 1

    while True:
        resultado = ciclo_seguro(cliente, indicadores)
        espera = horas * 3600 if resultado is not None else min(horas * 3600, REINTENTO_CICLO)
        log.info("Siguiente ciclo en %.1f horas.", espera / 3600)
        esperar(espera)


if __name__ == "__main__":
    sys.exit(main())
