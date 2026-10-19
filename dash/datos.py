"""Lectura de la base. El dashboard solo usa las vistas de analisis, con el usuario dashboard."""
import os

import mysql.connector
import pandas as pd


def conectar():
    """Abre una conexión. La contraseña sale del secreto de Docker."""
    with open(os.environ["DB_PASSWORD_FILE"], encoding="utf-8") as archivo:
        clave = archivo.read().rstrip("\r\n")
    return mysql.connector.connect(
        host=os.environ.get("DB_HOST", "mysql"),
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ.get("DB_USER", "dashboard"),
        password=clave,
        database="analisis",
        charset="utf8mb4",
        time_zone="+00:00",
        connection_timeout=5,
    )


def consultar(sql, datos=()):
    """Corre una consulta y regresa una tabla de pandas."""
    cx = conectar()
    try:
        cursor = cx.cursor()
        cursor.execute(sql, datos)
        columnas = [c[0] for c in cursor.description]
        filas = cursor.fetchall()
        cursor.close()
    finally:
        cx.close()
    return pd.DataFrame(filas, columns=columnas)


# Lo que se lee se guarda en memoria hasta que llega una carga nueva (cambia la "versión").
_memoria = {}


def recordar(clave, version, leer):
    guardado = _memoria.get(clave)
    if guardado is None or guardado[0] != version:
        guardado = (version, leer())
        _memoria[clave] = guardado
    return guardado[1]


def estado():
    """Regresa (versión, fecha de la última carga que salió bien).

    La versión cambia cuando empieza una carga y otra vez cuando termina. Así, si la página
    leyó los datos a media carga, los vuelve a leer al final.
    """
    tabla = consultar("SELECT COALESCE(MAX(carga_id), 0) AS ultima, MAX(fin) AS fin, "
                      "MAX(ultima_carga_ok) AS ultima_ok "
                      "FROM v_ultima_carga WHERE indicador_codigo IS NOT NULL")
    fila = tabla.iloc[0]
    return f"{int(fila.ultima)}|{fila.fin}", fila.ultima_ok


def indicadores(version):
    return recordar("indicadores", version,
                    lambda: consultar("SELECT * FROM v_indicadores ORDER BY codigo"))


def ubicaciones(version):
    return recordar("ubicaciones", version, lambda: consultar("SELECT * FROM v_ubicaciones"))


def series(version, indicador):
    return recordar(("series", indicador), version, lambda: consultar(
        "SELECT * FROM v_series WHERE indicador_codigo = %s AND desagregacion = 'TOTAL' "
        "ORDER BY ubicacion_codigo, anio", (indicador,)))


def ultimo_dato(version, indicador):
    return recordar(("ultimo", indicador), version, lambda: consultar(
        "SELECT * FROM v_ultimo_dato WHERE indicador_codigo = %s AND desagregacion = 'TOTAL'",
        (indicador,)))
