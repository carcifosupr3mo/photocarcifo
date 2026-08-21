#!/usr/bin/env bash
# Manutenzione notturna: salva tutto, aggiorna, verifica.
#
# Prima di toccare qualsiasi cosa viene creata una copia completa del sito
# in backup/aggiornamenti, di cui si conservano le tre piu' recenti. I
# backup creati a mano finiscono in backup/personali e non vengono mai
# cancellati automaticamente.
#
# Se dopo l'aggiornamento il sito non risponde, viene ripristinata da sola
# la copia appena creata.

set -uo pipefail
export DEBIAN_FRONTEND=noninteractive

APP=/opt/photocarcifo
BACKUP="$APP/backup/aggiornamenti"
TENERE=3
LOG=/var/log/photocarcifo-notte.log
OGGI=$(date +%F)
COPIA="$BACKUP/prima-aggiornamento-$OGGI.tar.gz"

exec >>"$LOG" 2>&1
echo ""
echo "═══════════ $(date '+%d/%m/%Y %H:%M') — manutenzione notturna ═══════════"

# ---------- 1. Controlli preliminari ----------
echo "▸ Controlli"
if ! mountpoint -q /mnt/magazzino; then
    echo "  archivio non collegato, provo a montarlo"
    mount /mnt/magazzino 2>/dev/null
fi
mountpoint -q /mnt/magazzino && echo "  archivio: collegato" || echo "  archivio: NON disponibile"

LIBERI=$(df --output=avail -BG / | tail -1 | tr -dc '0-9')
echo "  spazio libero: ${LIBERI} GB"
if [ "$LIBERI" -lt 8 ]; then
    echo "  ✗ meno di 8 GB liberi: mi fermo per sicurezza"
    exit 1
fi

# ---------- 2. Copia di sicurezza ----------
echo "▸ Copia di sicurezza"
mkdir -p "$BACKUP" "$APP/backup/personali"

sqlite3 "$APP/data/photocarcifo.db" ".backup '/tmp/db-notte.sqlite'" 2>/dev/null \
  && echo "  database congelato" || echo "  ATTENZIONE: copia database non riuscita"

# Le esclusioni vanno scritte prima del percorso, altrimenti tar le
# ignora. Restano fuori librerie, miniature e vecchie copie: si
# rigenerano da sole e peserebbero gigabyte inutili.
tar --exclude='venv' \
    --exclude='__pycache__' \
    --exclude='cache' \
    --exclude='backup' \
    --exclude='*.tar.gz' \
    --exclude='*.sqlite' \
    --exclude='EMERGENZA-NATH' \
    -czf "$COPIA" -C /opt photocarcifo 2>/dev/null

if [ -s "$COPIA" ]; then
    # aggiungo la copia coerente del database e le configurazioni di sistema
    mkdir -p /tmp/extra/config
    cp /tmp/db-notte.sqlite /tmp/extra/database.sqlite 2>/dev/null
    cp -r /etc/nginx/sites-available /tmp/extra/config/nginx 2>/dev/null
    mkdir -p /tmp/extra/config/systemd /tmp/extra/config/script
    cp /etc/systemd/system/photocarcifo* /tmp/extra/config/systemd/ 2>/dev/null
    cp /usr/local/bin/photocarcifo-* /tmp/extra/config/script/ 2>/dev/null
    tar -czf "${COPIA%.tar.gz}-extra.tar.gz" -C /tmp extra 2>/dev/null
    rm -rf /tmp/extra /tmp/db-notte.sqlite
    echo "  creata: $(basename "$COPIA") ($(du -h "$COPIA" | cut -f1))"
else
    echo "  ✗ copia non riuscita: interrompo, non aggiorno nulla"
    exit 1
fi

# rotazione: conservo solo le tre piu' recenti
cd "$BACKUP" || exit 1
ls -1t prima-aggiornamento-*.tar.gz 2>/dev/null | tail -n +$((TENERE + 1)) | while read -r v; do
    rm -f "$v" "${v%.tar.gz}-extra.tar.gz"
    echo "  rimossa copia vecchia: $v"
done
echo "  copie conservate: $(ls -1 prima-aggiornamento-*.tar.gz 2>/dev/null | grep -vc extra)"
cd "$APP" || exit 1

# ---------- 3. Aggiornamenti ----------
echo "▸ Aggiornamenti di sistema"
apt-get update -qq
PRIMA=$(dpkg -l | grep -c '^ii')
apt-get -y -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" upgrade
apt-get -y autoremove --purge >/dev/null
apt-get -y autoclean >/dev/null
DOPO=$(dpkg -l | grep -c '^ii')
echo "  pacchetti: $PRIMA → $DOPO"

echo "▸ Aggiornamenti delle librerie del sito"
sudo -u photocarcifo "$APP/venv/bin/pip" install --quiet --upgrade pip 2>/dev/null

# Librerie tenute ferme di proposito. Non sono in ritardo per dimenticanza:
# passare alle versioni nuove richiede di riscrivere parti del sito (in
# Starlette 1.x le chiamate ai modelli hanno cambiato forma, e sono 33).
# Aggiornarle di notte, senza nessuno che guardi, lascerebbe il sito giu'
# fino al mattino. Vanno fatte a mano, guardando che tutto risponda.
FERME="fastapi starlette uvicorn pydantic pydantic-core pydantic_core pydantic-settings"

# Il formato "freeze" non elenca nulla in questa versione di pip: lo script
# credeva quindi che fosse sempre tutto aggiornato e da mesi non aggiornava
# niente, in silenzio. Si legge il formato normale, saltando le due righe
# di intestazione e tenendo solo il nome.
SCADUTE=$(sudo -u photocarcifo "$APP/venv/bin/pip" list --outdated 2>/dev/null \
          | tail -n +3 | awk '{print $1}')
# tolgo quelle da non toccare
for f in $FERME; do
    SCADUTE=$(echo "$SCADUTE" | grep -vix "$f")
done
SCADUTE=$(echo "$SCADUTE" | tr -s '\n' ' ' | sed 's/^ *//;s/ *$//')

if [ -n "$SCADUTE" ]; then
    echo "  da aggiornare: $SCADUTE"
    # shellcheck disable=SC2086
    if sudo -u photocarcifo "$APP/venv/bin/pip" install --quiet --upgrade $SCADUTE 2>/dev/null; then
        # Un aggiornamento puo' lasciare due librerie che non si parlano
        # piu' fra loro: il sito continuerebbe a girare, ma al primo
        # riavvio non ripartirebbe. Meglio accorgersene adesso.
        if sudo -u photocarcifo "$APP/venv/bin/pip" check >/dev/null 2>&1; then
            echo "  librerie aggiornate"
        else
            echo "  ATTENZIONE: librerie incompatibili fra loro dopo l'aggiornamento"
            sudo -u photocarcifo "$APP/venv/bin/pip" check 2>&1 | sed 's/^/    /'
        fi
    else
        echo "  ATTENZIONE: alcune non aggiornate"
    fi
else
    echo "  già tutte aggiornate"
fi
[ -n "$FERME" ] && echo "  tenute ferme di proposito: $FERME"

echo "▸ Certificati"
certbot renew --quiet --no-random-sleep-on-renew 2>/dev/null \
  && echo "  verificati" || echo "  nessun rinnovo necessario"

# ---------- 4. Manutenzione dei dati ----------
echo "▸ Archivio e database"
if mountpoint -q /mnt/magazzino; then
    systemctl start photocarcifo-scan.service 2>/dev/null
    sleep 10
    echo "  rilettura archivio avviata"
fi

sqlite3 "$APP/data/photocarcifo.db" "
  DELETE FROM logs WHERE ts < datetime('now','-60 days');
  DELETE FROM stats WHERE ts < datetime('now','-400 days');
  DELETE FROM ricerche WHERE ultimo_at < datetime('now','-400 days');
  -- Tentativi di accesso falliti: le righe vecchie non fermano piu'
  -- nessuno, contano solo quelle recenti.
  DELETE FROM tentativi WHERE quando < strftime('%s','now') - 86400;
  DELETE FROM preferiti WHERE media_id NOT IN (SELECT id FROM media);
  PRAGMA optimize;
  VACUUM;" 2>/dev/null && echo "  database ottimizzato"

FOTO=$(sqlite3 "$APP/data/photocarcifo.db" "SELECT COUNT(*) FROM media;" 2>/dev/null)
echo "  fotografie in archivio: $FOTO"

# registri e pacchetti scaricati occupano spazio inutile,
# che finirebbe anche nei backup del contenitore
journalctl --vacuum-size=100M -q 2>/dev/null
apt-get clean >/dev/null 2>&1
rm -rf /tmp/app-guasta-* 2>/dev/null

if [ -d /mnt/magazzino-rw/_CESTINO ]; then
    N=$(find /mnt/magazzino-rw/_CESTINO -type f 2>/dev/null | wc -l)
    D=$(du -sh /mnt/magazzino-rw/_CESTINO 2>/dev/null | cut -f1)
    echo "  cestino: $N file, $D"
    V=$(find /mnt/magazzino-rw/_CESTINO -maxdepth 1 -type d -mtime +90 2>/dev/null | wc -l)
    [ "$V" -gt 0 ] && echo "  ⚠ $V gruppi nel cestino da oltre 90 giorni"
fi

# ---------- 5. Riavvio e verifica ----------
echo "▸ Riavvio"
find "$APP/app" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null
systemctl restart photocarcifo
systemctl reload nginx
sleep 8

CODICE=$(curl -s -o /dev/null -m 20 -w '%{http_code}' http://127.0.0.1:8000/healthz)
echo "  risposta del sito: $CODICE"

if [ "$CODICE" != "200" ]; then
    echo "  ✗ il sito non risponde: secondo tentativo"
    systemctl restart photocarcifo
    sleep 12
    CODICE=$(curl -s -o /dev/null -m 20 -w '%{http_code}' http://127.0.0.1:8000/healthz)
    echo "  secondo tentativo: $CODICE"
fi

if [ "$CODICE" != "200" ]; then
    echo "  ✗✗ RIPRISTINO AUTOMATICO della copia di stanotte"
    systemctl stop photocarcifo
    mv "$APP/app" "/tmp/app-guasta-$(date +%H%M)" 2>/dev/null
    tar -xzf "$COPIA" -C /opt photocarcifo/app 2>/dev/null
    chown -R photocarcifo:photocarcifo "$APP/app"
    systemctl start photocarcifo
    sleep 10
    CODICE=$(curl -s -o /dev/null -m 20 -w '%{http_code}' http://127.0.0.1:8000/healthz)
    echo "  dopo il ripristino: $CODICE"
    [ "$CODICE" = "200" ] && echo "  ✓ sito recuperato" || echo "  ✗ SERVE INTERVENTO MANUALE"
fi

# la mappa deve rispecchiare sempre lo stato reale del sito
if [ -x /usr/local/bin/photocarcifo-mappa.sh ]; then
    /usr/local/bin/photocarcifo-mappa.sh >/dev/null 2>&1 \
      && echo "  mappa del sito aggiornata"
fi

# ---------- 6. Riepilogo ----------
echo "▸ Riepilogo"
echo "  spazio libero: $(df -h / | awk 'NR==2{print $4}')"
echo "  copie disponibili:"
ls -1t "$BACKUP"/prima-aggiornamento-*.tar.gz 2>/dev/null | grep -v extra | while read -r f; do
    echo "    $(basename "$f")  $(du -h "$f" | cut -f1)"
done
PERS=$(ls -1 "$APP/backup/personali" 2>/dev/null | wc -l)
echo "  copie personali conservate: $PERS"

if [ -f /var/run/reboot-required ]; then
    echo "▸ Kernel aggiornato: riavvio il contenitore fra un minuto"
    echo "═══════════ fine (con riavvio) ═══════════"
    shutdown -r +1 "Manutenzione Photocarcifo"
    exit 0
fi

echo "═══════════ $(date '+%H:%M') — fine ═══════════"
