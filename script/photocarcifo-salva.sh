#!/usr/bin/env bash
# Copia di sicurezza creata a mano. Finisce in backup/personali e non
# viene mai rimossa dalla manutenzione notturna.
#   uso:  photocarcifo-salva.sh [descrizione]
APP=/opt/photocarcifo
DEST="$APP/backup/personali"
mkdir -p "$DEST"
NOME="${1:-manuale}"
NOME=$(echo "$NOME" | tr ' /' '--' | tr -cd '[:alnum:]-_')
FILE="$DEST/$(date +%F_%H-%M)-$NOME.tar.gz"

sqlite3 "$APP/data/photocarcifo.db" ".backup '/tmp/db-manuale.sqlite'"
mkdir -p /tmp/salva/config
cp /tmp/db-manuale.sqlite /tmp/salva/database.sqlite
cp -r /etc/nginx/sites-available /tmp/salva/config/nginx 2>/dev/null
mkdir -p /tmp/salva/config/systemd /tmp/salva/config/script
cp /etc/systemd/system/photocarcifo* /tmp/salva/config/systemd/ 2>/dev/null
cp /usr/local/bin/photocarcifo-* /tmp/salva/config/script/ 2>/dev/null
cp -r "$APP/app" /tmp/salva/app
rm -rf /tmp/salva/EMERGENZA-NATH 2>/dev/null
cp "$APP/.env" /tmp/salva/env-configurazione 2>/dev/null
find /tmp/salva -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null

tar -czf "$FILE" -C /tmp salva
rm -rf /tmp/salva /tmp/db-manuale.sqlite
chmod 600 "$FILE"

echo "Copia creata: $FILE"
du -h "$FILE" | cut -f1 | xargs echo "Dimensione:"
echo ""
echo "Copie personali presenti:"
ls -1sh "$DEST" | sed 's/^/  /'
