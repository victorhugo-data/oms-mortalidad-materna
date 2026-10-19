#!/bin/bash
# Saca un respaldo de las tres capas (crudo, limpio y analisis) en formato SQL.
# Se corre dentro del contenedor de MySQL; el respaldo sale por la pantalla, así que se guarda
# mandándolo a un archivo de la carpeta respaldos/ (no se sube a Git):
#   PowerShell:   cmd /c "docker compose exec -T mysql bash < mysql\respaldar.sh > respaldos\respaldo.sql"
#   Linux o Mac:  docker compose exec -T mysql bash < mysql/respaldar.sh > respaldos/respaldo.sql

MYSQL_PWD="$(cat /run/secrets/mysql_root_password)" mysqldump -uroot --default-character-set=utf8mb4 \
  --single-transaction --triggers --routines --no-tablespaces --set-gtid-purged=OFF \
  --databases crudo limpio analisis
