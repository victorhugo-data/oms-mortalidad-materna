#!/bin/bash
# Carga un respaldo hecho con respaldar.sh. Reemplaza lo que haya en crudo, limpio y analisis
# por lo del respaldo; los usuarios y sus contraseñas no cambian.
# Se corre dentro del contenedor de MySQL, desde la carpeta del proyecto. Primero se detiene el
# recolector y se copia el respaldo al contenedor:
#   docker compose stop recolector
#   docker compose cp respaldos/respaldo.sql mysql:/tmp/respaldo.sql
#   PowerShell:   cmd /c "docker compose exec -T mysql bash < mysql\restaurar.sh"
#   Linux o Mac:  docker compose exec -T mysql bash < mysql/restaurar.sh
#   docker compose start recolector

set -e
if [ ! -s /tmp/respaldo.sql ]; then
  echo "No encontré /tmp/respaldo.sql: primero cópialo con docker compose cp."
  exit 1
fi
MYSQL_PWD="$(cat /run/secrets/mysql_root_password)" mysql -uroot --default-character-set=utf8mb4 < /tmp/respaldo.sql
rm -f /tmp/respaldo.sql
echo "Respaldo cargado."
