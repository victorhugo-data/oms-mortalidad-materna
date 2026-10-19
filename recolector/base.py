"""Lo que el recolector lee y escribe en MySQL (usuario recolector: sin permiso de borrar)."""
import logging
import os

import mysql.connector

from salud import esperar, latido

log = logging.getLogger("recolector")
TANDA = 1000   # filas por cada INSERT


def conectar(intentos=5):
    """Abre una conexión. La contraseña sale del secreto de Docker."""
    with open(os.environ["DB_PASSWORD_FILE"], encoding="utf-8") as archivo:
        clave = archivo.read().rstrip("\r\n")
    for intento in range(1, intentos + 1):
        try:
            return mysql.connector.connect(
                host=os.environ.get("DB_HOST", "mysql"),
                port=int(os.environ.get("DB_PORT", "3306")),
                user=os.environ.get("DB_USER", "recolector"),
                password=clave,
                charset="utf8mb4",
                time_zone="+00:00",
                autocommit=False,
                connection_timeout=10,
            )
        except mysql.connector.Error as error:
            if intento == intentos:
                raise
            log.warning("No pude conectar con MySQL (%s); reintento en 5 s", error)
            esperar(5)


def una_fila(cx, sql, datos=()):
    cursor = cx.cursor()
    cursor.execute(sql, datos)
    fila = cursor.fetchone()
    cursor.close()
    return fila


def ejecutar(cx, sql, datos=()):
    cursor = cx.cursor()
    cursor.execute(sql, datos)
    filas = cursor.rowcount
    cursor.close()
    return filas


def ejecutar_varias(cx, sql, filas):
    cursor = cx.cursor()
    for inicio in range(0, len(filas), TANDA):
        cursor.executemany(sql, filas[inicio:inicio + TANDA])
    cursor.close()


# Turno: solo un recolector carga a la vez (por ejemplo, el del ciclo y uno corrido a mano).

def tomar_turno(cx, segundos):
    for _ in range(max(1, segundos // 30)):
        latido()
        if una_fila(cx, "SELECT GET_LOCK('oms_recolector', 30)")[0] == 1:
            return True
    return False


def soltar_turno(cx):
    una_fila(cx, "SELECT RELEASE_LOCK('oms_recolector')")


# Cargas (crudo.cargas) y respuestas de la API (crudo.respuestas_api).

def cerrar_interrumpidas(cx):
    """Las cargas que quedaron EN_CURSO porque el recolector se detuvo a medias pasan a ERROR."""
    filas = ejecutar(cx, "UPDATE crudo.cargas SET estado = 'ERROR', fin = NOW(3), mensaje = %s "
                         "WHERE estado = 'EN_CURSO'",
                     ("Interrumpida: el recolector se detuvo antes de terminar.",))
    cx.commit()
    return filas


def abrir_carga(cx, indicador, url):
    cursor = cx.cursor()
    cursor.execute("INSERT INTO crudo.cargas (indicador_codigo, url_consulta) VALUES (%s, %s)",
                   (indicador, url))
    carga_id = cursor.lastrowid
    cursor.close()
    cx.commit()
    return carga_id


def guardar_respuesta(cx, carga_id, texto):
    """Se guarda en su propia transacción: se queda aunque falle lo demás."""
    ejecutar(cx, "INSERT INTO crudo.respuestas_api (carga_id, cuerpo) VALUES (%s, %s)", (carga_id, texto))
    cx.commit()


def cerrar_carga(cx, carga_id, recibidos, nuevos, cambiados, omitidos, mensaje):
    """Se anota en la misma transacción que los datos: o queda todo, o nada."""
    ejecutar(cx, "UPDATE crudo.cargas SET estado = 'OK', fin = NOW(3), recibidos = %s, nuevos = %s, "
                 "cambiados = %s, omitidos = %s, mensaje = %s WHERE id = %s",
             (recibidos, nuevos, cambiados, omitidos, mensaje, carga_id))


def marcar_error(cx, carga_id, recibidos, mensaje):
    cx.rollback()
    ejecutar(cx, "UPDATE crudo.cargas SET estado = 'ERROR', fin = NOW(3), recibidos = %s, mensaje = %s "
                 "WHERE id = %s", (recibidos, mensaje[:2000], carga_id))
    cx.commit()


# Ubicaciones e indicadores.

def leer_ubicaciones(cx):
    cursor = cx.cursor()
    cursor.execute("SELECT codigo, tipo, nombre, region_codigo FROM limpio.ubicaciones")
    ubicaciones = {codigo: (tipo, nombre, region) for codigo, tipo, nombre, region in cursor}
    cursor.close()
    return ubicaciones


def insertar_ubicaciones(cx, filas):
    ejecutar_varias(cx, "INSERT INTO limpio.ubicaciones (codigo, tipo, nombre, region_codigo) "
                        "VALUES (%s, %s, %s, %s)",
                    [(codigo, *datos) for codigo, datos in filas.items()])


def actualizar_ubicaciones(cx, filas):
    ejecutar_varias(cx, "UPDATE limpio.ubicaciones SET tipo = %s, nombre = %s, region_codigo = %s "
                        "WHERE codigo = %s",
                    [(*datos, codigo) for codigo, datos in filas.items()])


def leer_nombres_indicadores(cx):
    cursor = cx.cursor()
    cursor.execute("SELECT codigo, nombre FROM limpio.indicadores")
    nombres = dict(cursor.fetchall())
    cursor.close()
    return nombres


def crear_indicador(cx, codigo, nombre):
    ejecutar(cx, "INSERT INTO limpio.indicadores (codigo, nombre) VALUES (%s, %s)", (codigo, nombre))


def renombrar_indicador(cx, codigo, nombre):
    ejecutar(cx, "UPDATE limpio.indicadores SET nombre = %s WHERE codigo = %s", (nombre, codigo))


# Observaciones.

def leer_observaciones(cx, indicador):
    """{(ubicación, desagregación, año): valores} de lo que ya está guardado."""
    cursor = cx.cursor()
    cursor.execute("SELECT ubicacion_codigo, desagregacion, anio, periodo, valor, valor_min, valor_max, "
                   "fuente, fecha_publicacion_oms FROM limpio.observaciones WHERE indicador_codigo = %s",
                   (indicador,))
    guardadas = {}
    for ubicacion, grupo, anio, periodo, valor, minimo, maximo, fuente, fecha in cursor:
        guardadas[(ubicacion, grupo, anio)] = {
            "periodo": periodo, "valor": valor, "valor_min": minimo, "valor_max": maximo,
            "fuente": fuente, "fecha_publicacion_oms": fecha}
    cursor.close()
    return guardadas


def insertar_observaciones(cx, indicador, carga_id, filas):
    ejecutar_varias(
        cx,
        "INSERT INTO limpio.observaciones (indicador_codigo, ubicacion_codigo, desagregacion, anio, periodo, "
        "valor, valor_min, valor_max, fuente, fecha_publicacion_oms, carga_id) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        [(indicador, ubicacion, grupo, anio, v["periodo"], v["valor"], v["valor_min"], v["valor_max"],
          v["fuente"], v["fecha_publicacion_oms"], carga_id)
         for (ubicacion, grupo, anio), v in filas.items()])


def actualizar_observaciones(cx, indicador, carga_id, filas):
    """El trigger de la base guarda la versión anterior en el historial."""
    ejecutar_varias(
        cx,
        "UPDATE limpio.observaciones SET periodo = %s, valor = %s, valor_min = %s, valor_max = %s, "
        "fuente = %s, fecha_publicacion_oms = %s, carga_id = %s "
        "WHERE indicador_codigo = %s AND ubicacion_codigo = %s AND desagregacion = %s AND anio = %s",
        [(v["periodo"], v["valor"], v["valor_min"], v["valor_max"], v["fuente"], v["fecha_publicacion_oms"],
          carga_id, indicador, ubicacion, grupo, anio)
         for (ubicacion, grupo, anio), v in filas.items()])
