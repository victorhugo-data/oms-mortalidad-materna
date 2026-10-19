#!/bin/bash
# Revisa los datos que cargó el recolector, como los ve el dashboard (usuario dashboard).
# No cambia nada. Se corre dentro del contenedor de MySQL, desde la carpeta del proyecto:
#   PowerShell:   cmd /c "docker compose exec -T mysql bash < mysql\revisar_datos.sh"
#   Linux o Mac:  docker compose exec -T mysql bash < mysql/revisar_datos.sh

fallas=0

consulta() {
  MYSQL_PWD="$(cat /run/secrets/dashboard_password)" mysql --default-character-set=utf8mb4 -udashboard "$@" 2>&1
}

# Compara un dato con la cifra verificada en la API (valor, mínimo y máximo con un decimal).
revisar_dato() {
  local descripcion="$1" indicador="$2" ubicacion="$3" anio="$4" esperado="$5" obtenido
  obtenido="$(consulta -N -B -e "
    SELECT CONCAT_WS(' ', CAST(valor AS DECIMAL(10,1)), CAST(valor_min AS DECIMAL(10,1)),
                          CAST(valor_max AS DECIMAL(10,1)))
      FROM analisis.v_series
     WHERE indicador_codigo = '$indicador' AND ubicacion_codigo = '$ubicacion'
       AND anio = $anio AND desagregacion = 'TOTAL'")"
  if [ "$obtenido" = "$esperado" ]; then
    echo "OK     $descripcion: $obtenido"
  else
    echo "FALLA  $descripcion: salió '$obtenido' y la API dice $esperado"
    fallas=$((fallas + 1))
  fi
}

echo "== Indicadores con datos =="
consulta -t -e "SELECT codigo, observaciones, ubicaciones, anio_desde, anio_hasta, ultima_publicacion_oms
                  FROM analisis.v_indicadores ORDER BY codigo"

echo
echo "== Última carga de cada indicador (la del catálogo va con indicador vacío) =="
consulta -t -e "SELECT indicador_codigo, carga_id, estado, recibidos, nuevos, cambiados, omitidos,
                       inicio, fin, LEFT(mensaje, 60) AS mensaje
                  FROM analisis.v_ultima_carga ORDER BY indicador_codigo"

echo
echo "== Cifras verificadas en la API (valor, mínimo y máximo) =="
revisar_dato "Mundo 2023"         MDG_0000000026 GLOBAL 2023 "197.3 174.5 234.0"
revisar_dato "América 2023"       MDG_0000000026 AMR    2023 "58.5 52.3 66.3"
revisar_dato "México 2019"        MDG_0000000026 MEX    2019 "43.3 35.8 49.8"
revisar_dato "México 2020"        MDG_0000000026 MEX    2020 "61.5 47.3 80.4"
revisar_dato "México 2021"        MDG_0000000026 MEX    2021 "103.9 60.6 175.7"
revisar_dato "México 2023"        MDG_0000000026 MEX    2023 "42.1 31.7 49.9"
revisar_dato "Partos México 2012" MDG_0000000025 MEX    2012 "100.0"
if [ -n "$(consulta -N -B -e "SELECT 1 FROM analisis.v_indicadores WHERE codigo = 'WHS4_154'")" ]; then
  revisar_dato "Control prenatal México 2012" WHS4_154 MEX 2012 "91.0"
fi

echo
echo "== Partos atendidos en México: el cambio de fuente de 2018 =="
consulta -t -e "SELECT anio, periodo, CAST(valor AS DECIMAL(10,1)) AS valor, cambio_fuente,
                       LEFT(TRIM(fuente), 55) AS fuente
                  FROM analisis.v_series
                 WHERE indicador_codigo = 'MDG_0000000025' AND ubicacion_codigo = 'MEX' AND anio >= 2012
                 ORDER BY anio"

echo
echo "== Acentos =="
consulta -N -B -e "SELECT CONCAT('Con utf8mb4:        ', GROUP_CONCAT(nombre ORDER BY codigo SEPARATOR ', '))
                     FROM analisis.v_ubicaciones WHERE codigo IN ('CUW', 'TUR')"
MYSQL_PWD="$(cat /run/secrets/dashboard_password)" mysql -udashboard -N -B -e "
  SELECT CONCAT('Terminal de MySQL:  ', GROUP_CONCAT(nombre ORDER BY codigo SEPARATOR ', '))
    FROM analisis.v_ubicaciones WHERE codigo IN ('CUW', 'TUR')" 2>&1

echo
if [ "$fallas" -eq 0 ]; then
  echo "Resultado de los datos: todo bien."
else
  echo "Resultado de los datos: $fallas falla(s)."
fi
