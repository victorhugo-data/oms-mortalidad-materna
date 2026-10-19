#!/bin/bash
# Crea los usuarios que usan los otros contenedores, cada uno con lo justo:
#   recolector: lee y escribe en crudo y limpio, pero no puede borrar.
#   dashboard:  solo lee las vistas de analisis.
# Las contraseñas salen de los secretos de Docker (la carpeta secrets/).

# Lee una contraseña y la deja lista para ponerla entre comillas en SQL.
clave_para_sql() {
  local archivo="/run/secrets/$1" clave
  clave="$(cat "$archivo")" || return 1
  if [ -z "$clave" ]; then
    echo "La contraseña en $archivo está vacía." >&2
    return 1
  fi
  case "$clave" in
    *[[:space:][:cntrl:]]*)
      echo "La contraseña en $archivo tiene espacios o saltos de línea; créala de nuevo sin ellos." >&2
      return 1
      ;;
  esac
  printf '%s' "$clave" | sed -e 's/\\/\\\\/g' -e "s/'/''/g"
}

crear_usuarios() {
  local clave_recolector clave_dashboard
  clave_recolector="$(clave_para_sql recolector_password)" || return 1
  clave_dashboard="$(clave_para_sql dashboard_password)" || return 1

  MYSQL_PWD="$(cat /run/secrets/mysql_root_password)" mysql --protocol=socket \
    --socket="${SOCKET:-/var/run/mysqld/mysqld.sock}" -uroot <<SQL || return 1
CREATE USER 'recolector'@'%' IDENTIFIED BY '${clave_recolector}';
GRANT SELECT, INSERT, UPDATE ON crudo.*  TO 'recolector'@'%';
GRANT SELECT, INSERT, UPDATE ON limpio.* TO 'recolector'@'%';

CREATE USER 'dashboard'@'%' IDENTIFIED BY '${clave_dashboard}';
GRANT SELECT ON analisis.* TO 'dashboard'@'%';
SQL

  echo "Usuarios recolector y dashboard creados."
}

crear_usuarios
