#!/bin/bash
# Revisa que la base quedó bien armada: esquemas, tablas, vistas, fichas y permisos.
# No cambia nada. Se corre dentro del contenedor de MySQL, desde la carpeta del proyecto:
#   PowerShell:   cmd /c "docker compose exec -T mysql bash < mysql\revisar_base.sh"
#   Linux o Mac:  docker compose exec -T mysql bash < mysql/revisar_base.sh

fallas=0

# Corre una consulta con un usuario: consulta <usuario> <sql> [opciones de mysql]
consulta() {
  local usuario="$1" sql="$2" secreto
  shift 2
  if [ "$usuario" = root ]; then secreto=mysql_root_password; else secreto="${usuario}_password"; fi
  MYSQL_PWD="$(cat "/run/secrets/$secreto")" mysql --default-character-set=utf8mb4 -u"$usuario" "$@" -e "$sql" 2>&1
}

# Compara un conteo con lo que debería salir.
revisar_cuenta() {
  local descripcion="$1" esperado="$2" sql="$3" obtenido
  obtenido="$(consulta root "$sql" -N -B)"
  if [ "$obtenido" = "$esperado" ]; then
    echo "OK     $descripcion: $obtenido"
  else
    echo "FALLA  $descripcion: salió '$obtenido' y debía ser $esperado"
    fallas=$((fallas + 1))
  fi
}

# Revisa que un usuario sí pueda hacer algo.
debe_poder() {
  local usuario="$1" descripcion="$2" sql="$3" salida
  if salida="$(consulta "$usuario" "$sql" -N -B)"; then
    echo "OK     $usuario $descripcion"
  else
    echo "FALLA  $usuario no $descripcion: $salida"
    fallas=$((fallas + 1))
  fi
}

# Revisa que a un usuario le nieguen algo.
no_debe_poder() {
  local usuario="$1" descripcion="$2" sql="$3" salida
  if salida="$(consulta "$usuario" "$sql" -N -B)"; then
    echo "FALLA  $usuario $descripcion, y no debería"
    fallas=$((fallas + 1))
  elif [[ "$salida" == *denied* ]]; then
    echo "OK     $usuario no $descripcion (acceso denegado)"
  else
    echo "FALLA  $usuario $descripcion: $salida"
    fallas=$((fallas + 1))
  fi
}

echo "== Base de datos =="
consulta root "SELECT VERSION() AS version, @@global.time_zone AS zona_horaria,
                      @@character_set_server AS codificacion" -t

echo
echo "== Estructura =="
revisar_cuenta "Esquemas crudo, limpio y analisis" 3 \
  "SELECT COUNT(*) FROM information_schema.schemata
    WHERE schema_name IN ('crudo', 'limpio', 'analisis')"
revisar_cuenta "Tablas" 6 \
  "SELECT COUNT(*) FROM information_schema.tables
    WHERE table_schema IN ('crudo', 'limpio') AND table_type = 'BASE TABLE'"
revisar_cuenta "Vistas" 5 \
  "SELECT COUNT(*) FROM information_schema.views WHERE table_schema = 'analisis'"
revisar_cuenta "Trigger del historial" 1 \
  "SELECT COUNT(*) FROM information_schema.triggers WHERE trigger_schema = 'limpio'"
revisar_cuenta "Fichas de indicadores" 3 \
  "SELECT COUNT(*) FROM limpio.indicadores"
revisar_cuenta "Usuarios recolector y dashboard" 2 \
  "SELECT COUNT(*) FROM mysql.user WHERE user IN ('recolector', 'dashboard') AND host = '%'"
revisar_cuenta "Usuarios root que entran desde fuera del contenedor" 0 \
  "SELECT COUNT(*) FROM mysql.user WHERE user = 'root' AND host <> 'localhost'"

echo
echo "== Permisos =="
debe_poder    dashboard  "puede leer analisis"     "SELECT COUNT(*) FROM analisis.v_indicadores"
no_debe_poder dashboard  "puede leer limpio"       "SELECT COUNT(*) FROM limpio.observaciones"
no_debe_poder dashboard  "puede leer crudo"        "SELECT COUNT(*) FROM crudo.cargas"
debe_poder    recolector "puede leer crudo"        "SELECT COUNT(*) FROM crudo.cargas"
debe_poder    recolector "puede leer limpio"       "SELECT COUNT(*) FROM limpio.observaciones"
no_debe_poder recolector "puede borrar en crudo"   "DELETE FROM crudo.cargas WHERE id = 0"
no_debe_poder recolector "puede borrar en limpio"  "DELETE FROM limpio.observaciones WHERE id = 0"

echo
echo "== Detalle =="
consulta root "SELECT table_schema AS esquema, table_name AS nombre, table_type AS tipo
                 FROM information_schema.tables
                WHERE table_schema IN ('crudo', 'limpio', 'analisis')
                ORDER BY table_schema, table_type, table_name" -t
consulta root "SELECT table_schema AS esquema, table_name AS tabla, constraint_name AS regla
                 FROM information_schema.table_constraints
                WHERE table_schema IN ('crudo', 'limpio') AND constraint_type = 'CHECK'
                ORDER BY table_schema, table_name, constraint_name" -t
consulta root "SELECT codigo, nombre, tipo_dato, direccion_deseable, meta
                 FROM limpio.indicadores ORDER BY codigo" -t
consulta root "SHOW GRANTS FOR 'recolector'@'%'" -t
consulta root "SHOW GRANTS FOR 'dashboard'@'%'" -t

echo
if [ "$fallas" -eq 0 ]; then
  echo "Resultado: todo bien."
else
  echo "Resultado: $fallas falla(s)."
fi
