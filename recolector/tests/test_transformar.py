"""Pruebas de la revisión y conversión, con registros reales de la API (registros_oms.json)."""
import copy
import json
from datetime import datetime
from pathlib import Path

import pytest

import transformar

REGISTROS = json.loads((Path(__file__).parent / "registros_oms.json").read_text(encoding="utf-8"))
MORTALIDAD, PARTOS, PRENATAL = "MDG_0000000026", "MDG_0000000025", "WHS4_154"


def registro(nombre):
    return copy.deepcopy(REGISTROS[nombre])


# Registros que sí pasan

def test_mortalidad_mexico_2021():
    llave, valores, tipo = transformar.fila_observacion(registro("mortalidad_mex_2021"), MORTALIDAD)
    assert llave == ("MEX", "TOTAL", 2021)
    assert tipo == "COUNTRY"
    assert valores["valor"] == 103.877921
    assert (valores["valor_min"], valores["valor_max"]) == (60.6342347, 175.6905246)
    assert valores["fuente"] is None
    assert valores["periodo"] == "2021"
    # 15:44:11.957 con zona +02:00 son las 13:44:11.957 en UTC
    assert valores["fecha_publicacion_oms"] == datetime(2025, 4, 10, 13, 44, 11, 957000)


def test_mundo_2023_y_fecha_con_dos_decimales():
    llave, valores, tipo = transformar.fila_observacion(registro("mortalidad_global_2023"), MORTALIDAD)
    assert (llave, tipo) == (("GLOBAL", "TOTAL", 2023), "GLOBAL")
    assert valores["valor"] == 197.305373477
    # ".38" son 380 milisegundos
    assert valores["fecha_publicacion_oms"] == datetime(2025, 4, 7, 4, 46, 44, 380000)


def test_partos_mexico_2012_guarda_la_fuente_tal_cual():
    original = registro("partos_mex_2012")
    _, valores, _ = transformar.fila_observacion(original, PARTOS)
    assert valores["valor"] == 100.0
    assert (valores["valor_min"], valores["valor_max"]) == (None, None)
    assert valores["fuente"] == original["Comments"]
    assert valores["fuente"].startswith("Doctor, nurse, partera (TBA)")


def test_fuente_con_espacio_al_inicio_y_salto_de_linea_no_se_toca():
    original = registro("partos_mex_2015")
    _, valores, _ = transformar.fila_observacion(original, PARTOS)
    assert valores["fuente"] == original["Comments"]
    assert valores["fuente"].startswith(" ") and "\n" in valores["fuente"]


def test_control_prenatal_con_periodo_de_encuesta():
    llave, valores, _ = transformar.fila_observacion(registro("prenatal_mex_2015"), PRENATAL)
    assert llave == ("MEX", "TOTAL", 2015)
    assert valores["periodo"] == "2013-2015"
    assert valores["valor"] == 94.3


# Registros que se omiten (sin cambiar nada: solo se quitan o se cruzan datos reales)

def test_sin_valor_numerico():
    r = registro("mortalidad_mex_2021")
    r["NumericValue"] = None
    with pytest.raises(transformar.Omitido, match="sin valor numérico"):
        transformar.fila_observacion(r, MORTALIDAD)


def test_rango_al_reves():
    r = registro("mortalidad_mex_2021")
    r["Low"], r["High"] = r["High"], r["Low"]
    with pytest.raises(transformar.Omitido, match="fuera de su rango"):
        transformar.fila_observacion(r, MORTALIDAD)


def test_registro_de_otro_indicador():
    with pytest.raises(transformar.Omitido, match="otro código"):
        transformar.fila_observacion(registro("partos_mex_2012"), MORTALIDAD)


def test_repetidos_en_la_misma_respuesta():
    r = registro("mortalidad_mex_2021")
    filas, tipos, omitidos = transformar.filas_observaciones([r, copy.deepcopy(r)], MORTALIDAD)
    assert list(filas) == [("MEX", "TOTAL", 2021)]
    assert tipos == {"MEX": "COUNTRY"}
    assert [motivo for motivo, _ in omitidos] == ["repetido en la respuesta"]


def test_desagregacion():
    r = registro("mortalidad_mex_2021")
    assert transformar.desagregacion(r) == "TOTAL"
    # Tipo y valor de dimensión tal como aparecen en otro indicador de la OMS (RSUD_540).
    r["Dim1Type"], r["Dim1"] = "SUBSTANCETYPEDISORDER", "SUBSTANCETYPEDISORDER_ALCOHOL_USE_AND_DISORDERS"
    assert transformar.desagregacion(r) == "SUBSTANCETYPEDISORDER:SUBSTANCETYPEDISORDER_ALCOHOL_USE_AND_DISORDERS"


# Comparación: qué es nuevo, qué cambió y qué sigue igual

def test_comparar():
    registros = [registro("partos_mex_2012"), registro("partos_mex_2015")]
    filas, _, _ = transformar.filas_observaciones(registros, PARTOS)
    guardadas = copy.deepcopy(filas)

    # Lo mismo que ya está guardado: nada nuevo ni cambiado (correrlo dos veces da nuevos 0 y cambiados 0).
    assert transformar.comparar(filas, guardadas) == ({}, {})

    # Si 2015 no estaba guardado, es nuevo.
    sin_2015 = {llave: v for llave, v in guardadas.items() if llave[2] != 2015}
    nuevas, cambiadas = transformar.comparar(filas, sin_2015)
    assert (list(nuevas), cambiadas) == ([("MEX", "TOTAL", 2015)], {})

    # Si lo guardado de 2012 tenía otra fecha de publicación (la de otro registro real), cambió.
    otra_fecha = transformar.fecha_utc(REGISTROS["partos_mex_2016"]["Date"])
    guardadas[("MEX", "TOTAL", 2012)]["fecha_publicacion_oms"] = otra_fecha
    nuevas, cambiadas = transformar.comparar(filas, guardadas)
    assert (nuevas, list(cambiadas)) == ({}, [("MEX", "TOTAL", 2012)])


# Catálogos y configuración

def test_catalogo_de_paises_y_regiones():
    filas, omitidos = transformar.filas_ubicaciones(
        [REGISTROS["pais_mex"], REGISTROS["pais_cuw"], REGISTROS["pais_xkx"]], "COUNTRY")
    assert filas == {
        "MEX": ("COUNTRY", "Mexico", "AMR"),
        "CUW": ("COUNTRY", "Curaçao", "AMR"),
        "XKX": ("COUNTRY", "Kosovo (in accordance with UN Security Council resolution 1244 (1999))", None),
    }
    assert omitidos == []
    assert transformar.filas_ubicaciones([REGISTROS["region_amr"]], "REGION")[0] == {
        "AMR": ("REGION", "Americas", None)}
    assert transformar.filas_ubicaciones([REGISTROS["mundo"]], "GLOBAL")[0] == {
        "GLOBAL": ("GLOBAL", "Global", None)}


def test_leer_indicadores():
    assert transformar.leer_indicadores(" MDG_0000000026, MDG_0000000025,,MDG_0000000026 ") == [
        "MDG_0000000026", "MDG_0000000025"]
    with pytest.raises(ValueError):
        transformar.leer_indicadores("MDG 26")
