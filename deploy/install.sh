#!/usr/bin/env bash
# =============================================================
# Photocarcifo - Script di installazione per Ubuntu Server 24.04
# Da eseguire come root sul container Proxmox (192.168.1.206)
#
#   chmod +x deploy/install.sh
#   sudo ./deploy/install.sh
# =============================================================
set -euo pipefail

APP_DIR="/opt/photocarcifo"
SERVICE_USER="photocarcifo"
MOUNT_POINT="/mnt/magazzino"
MOUNT_POINT_RW="/mnt/magazzino-rw"

echo "==> [1/8] Aggiornamento pacchetti e dipendenze di sistema"
apt-get update
apt-get install -y python3 python3-venv python3-pip nfs-common nginx openssl \
                   ffmpeg sqlite3 certbot python3-certbot-nginx

echo "==> [2/8] Creazione utente di servizio (senza login shell)"
if ! id "$SERVICE_USER" &>/dev/null; then
    useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

echo "==> [3/8] Copia dei file applicativi in $APP_DIR"
mkdir -p "$APP_DIR"
# Copia il contenuto della cartella del progetto (dove si trova questo script)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cp -r "$SCRIPT_DIR"/. "$APP_DIR"/
cd "$APP_DIR"

echo "==> [4/8] Creazione virtualenv e installazione dipendenze Python"
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

echo "==> [5/8] Preparazione file .env"
if [ ! -f "$APP_DIR/.env" ]; then
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    # Genera automaticamente una SECRET_KEY robusta
    SECRET="$(openssl rand -hex 32)"
    sed -i "s|^SECRET_KEY=.*|SECRET_KEY=${SECRET}|" "$APP_DIR/.env"
    echo "    -> .env creato con SECRET_KEY generata automaticamente."
    echo "    -> MODIFICA ADMIN_PASSWORD in $APP_DIR/.env prima del primo avvio!"
fi

echo "==> [6/8] Creazione mount point NAS ($MOUNT_POINT, $MOUNT_POINT_RW)"
mkdir -p "$MOUNT_POINT" "$MOUNT_POINT_RW"

# Mount NFSv4 (nessuna credenziale richiesta): un mount read-only e uno
# read-write sullo stesso export, usati da parti diverse dell'app.
FSTAB_LINE_RO="192.168.1.11:/volume1/photocarcifo  ${MOUNT_POINT}  nfs4  ro,_netdev,soft  0  0"
FSTAB_LINE_RW="192.168.1.11:/volume1/photocarcifo  ${MOUNT_POINT_RW}  nfs4  rw,_netdev,soft  0  0"

if ! grep -q "$MOUNT_POINT " /etc/fstab; then
    echo "$FSTAB_LINE_RO" >> /etc/fstab
fi
if ! grep -q "$MOUNT_POINT_RW " /etc/fstab; then
    echo "$FSTAB_LINE_RW" >> /etc/fstab
fi

systemctl daemon-reload || true
mount -a || echo "    !! Mount fallito: verifica il percorso NAS."

for mp in "$MOUNT_POINT" "$MOUNT_POINT_RW"; do
    if mountpoint -q "$mp"; then
        echo "    -> $mp montato correttamente."
    else
        # Una cartella vuota locale può sembrare valida a un semplice ls/exists
        # senza esserlo davvero: controllare sempre con mountpoint, non solo ls.
        echo "    !! $mp NON risulta montato (mountpoint -q fallito)."
    fi
done

echo "==> [7/8] Permessi e installazione servizi systemd + nginx"
chown -R "$SERVICE_USER":"$SERVICE_USER" "$APP_DIR/data"
chown -R "$SERVICE_USER":"$SERVICE_USER" "$APP_DIR"

# Solo le 5 unit base del repository. Le altre 22 unit runtime (bot, covers,
# db-backup, errori, mensile, monitor, notte, pregen, rapporto, sentinella,
# update, export-config) NON vengono ricreate qui: si ripristinano solo
# dall'export su NAS (_backup_sito/configurazione/systemd/) in caso di
# disaster recovery (vedi docs/DISASTER_RECOVERY.md §3.10). Questo script
# serve per un'installazione da zero, non per un ripristino.
cp "$APP_DIR/deploy/photocarcifo.service" /etc/systemd/system/photocarcifo.service
cp "$APP_DIR/deploy/photocarcifo-scan.service" /etc/systemd/system/photocarcifo-scan.service
cp "$APP_DIR/deploy/photocarcifo-scan.timer" /etc/systemd/system/photocarcifo-scan.timer
cp "$APP_DIR/deploy/photocarcifo-numeri.service" /etc/systemd/system/photocarcifo-numeri.service
cp "$APP_DIR/deploy/photocarcifo-numeri.timer" /etc/systemd/system/photocarcifo-numeri.timer

# La configurazione Nginx si installa SOLO se non c'e' gia'. Quella in uso su
# un sito avviato viene perfezionata a mano (certificati HTTPS, upload senza
# limite di dimensione, cache che salta i cookie degli album riservati):
# copiarci sopra il modello del progetto farebbe cadere il sito.
# Il file copiato qui e' solo un modello iniziale, non la configurazione di
# produzione: quella si ripristina dall'export DR in caso di disaster
# recovery (vedi docs/DISASTER_RECOVERY.md §3.12).
if [ ! -f /etc/nginx/sites-available/photocarcifo ]; then
    cp "$APP_DIR/deploy/nginx.conf" /etc/nginx/sites-available/photocarcifo
    ln -sf /etc/nginx/sites-available/photocarcifo /etc/nginx/sites-enabled/photocarcifo
    rm -f /etc/nginx/sites-enabled/default
else
    echo "    -> Configurazione Nginx gia' presente: lasciata com'e'."
    echo "       Il modello del progetto resta in $APP_DIR/deploy/nginx.conf"
fi

systemctl daemon-reload
systemctl enable --now photocarcifo.service
systemctl enable --now photocarcifo-scan.timer
systemctl enable --now photocarcifo-numeri.timer
nginx -t && systemctl restart nginx

echo "==> [8/8] Fatto!"
echo "-------------------------------------------------------------"
echo " Photocarcifo installato."
echo " Sito:       http://192.168.1.206"
echo " Dashboard:  http://192.168.1.206/admin"
echo ""
echo " PROSSIMI PASSI:"
echo "  1. Modifica ADMIN_PASSWORD in $APP_DIR/.env"
echo "  2. systemctl restart photocarcifo"
echo "  3. Lancia la prima scansione dalla dashboard o:"
echo "     sudo systemctl start photocarcifo-scan.service"
echo "-------------------------------------------------------------"
