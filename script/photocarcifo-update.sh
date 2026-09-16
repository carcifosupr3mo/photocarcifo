#!/usr/bin/env bash
# Manutenzione notturna Photocarcifo: aggiornamenti, scansione NAS, pulizia.
set -uo pipefail
export DEBIAN_FRONTEND=noninteractive
LOG=/var/log/photocarcifo-update.log
exec >>"$LOG" 2>&1
echo "===== $(date '+%F %T') avvio manutenzione ====="

echo "--- NAS ---"
if ! mountpoint -q /mnt/magazzino; then
    echo "NAS non montato, tento il mount"
    mount /mnt/magazzino || echo "ATTENZIONE: mount fallito"
fi
mountpoint -q /mnt/magazzino && echo "NAS ok" || { echo "NAS assente: salto la scansione"; SKIP_SCAN=1; }

echo "--- aggiornamento pacchetti ---"
apt-get update -qq
apt-get -y -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" upgrade
apt-get -y autoremove --purge
apt-get -y autoclean

echo "--- backup database ---"
mkdir -p /opt/photocarcifo/backup
sqlite3 /opt/photocarcifo/data/photocarcifo.db ".backup '/opt/photocarcifo/backup/db-$(date +%F).sqlite'"
find /opt/photocarcifo/backup -name 'db-*.sqlite' -mtime +14 -delete

# Copia sul NAS: se il contenitore si guasta, i backup restano al sicuro
if mountpoint -q /mnt/magazzino-rw; then
    mkdir -p /mnt/magazzino-rw/_backup_sito 2>/dev/null
    if cp "/opt/photocarcifo/backup/db-$(date +%F).sqlite" \
          /mnt/magazzino-rw/_backup_sito/ 2>/dev/null; then
        chmod 640 /mnt/magazzino-rw/_backup_sito/*.sqlite 2>/dev/null
        echo "copia su NAS eseguita"
        find /mnt/magazzino-rw/_backup_sito -name 'db-*.sqlite' -mtime +60 -delete 2>/dev/null
    else
        echo "copia su NAS non riuscita (permessi?)"
    fi
else
    echo "NAS in scrittura non montato: backup solo locale"
fi
echo "backup ok"

echo "--- scansione NAS ---"
if [ -z "${SKIP_SCAN:-}" ]; then
    systemctl start photocarcifo-scan.service
    sleep 5
    echo "scansione avviata"
fi

echo "--- ottimizzazione database ---"
sqlite3 /opt/photocarcifo/data/photocarcifo.db "PRAGMA optimize; VACUUM;" && echo "vacuum ok"

echo "--- pulizia log applicativi (oltre 60 giorni) ---"
sqlite3 /opt/photocarcifo/data/photocarcifo.db \
  "DELETE FROM logs WHERE ts < datetime('now','-60 days');
   DELETE FROM stats WHERE ts < datetime('now','-400 days');"
journalctl --vacuum-time=30d -q

echo "--- cestino ---"
if [ -d /mnt/magazzino-rw/_CESTINO ]; then
    DIM=$(du -sh /mnt/magazzino-rw/_CESTINO 2>/dev/null | cut -f1)
    NUM=$(find /mnt/magazzino-rw/_CESTINO -type f 2>/dev/null | wc -l)
    echo "nel cestino: $NUM file, $DIM"
    VECCHI=$(find /mnt/magazzino-rw/_CESTINO -maxdepth 1 -type d -mtime +90 2>/dev/null | wc -l)
    [ "$VECCHI" -gt 0 ] && echo "ATTENZIONE: $VECCHI gruppi hanno piu' di 90 giorni, valuta di svuotarli da DSM"
else
    echo "cestino vuoto"
fi

echo "--- riavvio servizi ---"
systemctl restart photocarcifo
systemctl reload nginx
sleep 5

echo "--- verifica ---"
CODE=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/healthz)
echo "healthz: $CODE"
if [ "$CODE" != "200" ]; then
    echo "SITO NON RISPONDE: secondo tentativo"
    systemctl restart photocarcifo
    sleep 8
    CODE=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/healthz)
    echo "healthz secondo tentativo: $CODE"
fi

if [ -f /var/run/reboot-required ]; then
    echo "kernel aggiornato: riavvio del container"
    echo "===== $(date '+%F %T') fine (con riavvio) ====="
    shutdown -r +1 "Manutenzione Photocarcifo"
    exit 0
fi

echo "===== $(date '+%F %T') fine ====="
