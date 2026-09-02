#!/usr/bin/env bash
# =============================================================
# Photocarcifo - Script di installazione per Ubuntu Server 22.04
# Da eseguire come root sul container Proxmox (192.0.2.10)
#
#   chmod +x deploy/install.sh
#   sudo ./deploy/install.sh
# =============================================================
set -euo pipefail

APP_DIR="/opt/photocarcifo"
SERVICE_USER="photocarcifo"
MOUNT_POINT="/mnt/magazzino"

echo "==> [1/8] Aggiornamento pacchetti e dipendenze di sistema"
apt-get update
apt-get install -y python3 python3-venv python3-pip cifs-utils nginx openssl

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

echo "==> [6/8] Creazione mount point NAS ($MOUNT_POINT)"
mkdir -p "$MOUNT_POINT"
if [ ! -f /etc/photocarcifo-smb.cred ]; then
    cat > /etc/photocarcifo-smb.cred <<'EOF'
username=IL_TUO_UTENTE_SYNOLOGY
password=LA_TUA_PASSWORD_SYNOLOGY
EOF
    chmod 600 /etc/photocarcifo-smb.cred
    echo "    -> Modifica /etc/photocarcifo-smb.cred con le credenziali Synology."
fi

# Aggiunge la voce a /etc/fstab se non presente (mount SMB read-only)
FSTAB_LINE="//192.0.2.20/Foto  ${MOUNT_POINT}  cifs  credentials=/etc/photocarcifo-smb.cred,ro,uid=${SERVICE_USER},iocharset=utf8,vers=3.0,nofail,x-systemd.automount  0  0"
if ! grep -q "$MOUNT_POINT" /etc/fstab; then
    echo "$FSTAB_LINE" >> /etc/fstab
    echo "    -> Voce fstab aggiunta. Monto adesso..."
    systemctl daemon-reload || true
    mount -a || echo "    !! Mount fallito: verifica credenziali/percorso NAS."
fi

echo "==> [7/8] Permessi e installazione servizi systemd + nginx"
chown -R "$SERVICE_USER":"$SERVICE_USER" "$APP_DIR/data"
chown -R "$SERVICE_USER":"$SERVICE_USER" "$APP_DIR"

cp "$APP_DIR/deploy/photocarcifo.service" /etc/systemd/system/photocarcifo.service
cp "$APP_DIR/deploy/photocarcifo-scan.service" /etc/systemd/system/photocarcifo-scan.service
cp "$APP_DIR/deploy/photocarcifo-scan.timer" /etc/systemd/system/photocarcifo-scan.timer
cp "$APP_DIR/deploy/photocarcifo-numeri.service" /etc/systemd/system/photocarcifo-numeri.service
cp "$APP_DIR/deploy/photocarcifo-numeri.timer" /etc/systemd/system/photocarcifo-numeri.timer

# La configurazione Nginx si installa SOLO se non c'e' gia'. Quella in uso su
# un sito avviato viene perfezionata a mano (certificati HTTPS, upload senza
# limite di dimensione, cache che salta i cookie degli album riservati):
# copiarci sopra il modello del progetto farebbe cadere il sito.
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
echo " Sito:       http://192.0.2.10"
echo " Dashboard:  http://192.0.2.10/admin"
echo ""
echo " PROSSIMI PASSI:"
echo "  1. Modifica /etc/photocarcifo-smb.cred con le credenziali NAS"
echo "  2. Modifica ADMIN_PASSWORD in $APP_DIR/.env"
echo "  3. systemctl restart photocarcifo"
echo "  4. Lancia la prima scansione dalla dashboard o:"
echo "     sudo systemctl start photocarcifo-scan.service"
echo "-------------------------------------------------------------"
