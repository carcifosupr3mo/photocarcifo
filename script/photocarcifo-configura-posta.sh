#!/usr/bin/env bash
# Configura l'invio del rapporto settimanale via posta.
# La password non compare a schermo e finisce solo nel file protetto.
set -uo pipefail

# Indirizzo che riceve (e manda, in From) il rapporto: da REPORT_EMAIL se
# gia' impostata nell'ambiente, altrimenti chiesta qui. Non va mai scritta
# a mano in questo file.
DEST="${REPORT_EMAIL:-}"
if [ -z "$DEST" ]; then
    read -rp "Indirizzo email che riceve il rapporto: " DEST
fi

echo "═══════════════════════════════════════════════"
echo "  Invio del rapporto via posta"
echo "═══════════════════════════════════════════════"
echo ""
echo "Serve la PASSWORD PER LE APP di Google (16 caratteri)."
echo "Incollala pure: non verra' mostrata mentre scrivi."
echo ""

command -v msmtp >/dev/null || {
    echo "Installo il sistema di invio…"
    apt-get update -qq && apt-get install -y msmtp msmtp-mta >/dev/null 2>&1
}

read -rsp "Password per le app: " PW
echo ""
PW=$(echo "$PW" | tr -d ' ')

if [ ${#PW} -ne 16 ]; then
    echo "✗ Devono essere 16 caratteri (ne ho letti ${#PW}). Riprova."
    exit 1
fi

umask 077
cat > /etc/msmtprc << EOF
defaults
auth           on
tls            on
tls_trust_file /etc/ssl/certs/ca-certificates.crt
logfile        /var/log/msmtp.log

account        gmail
host           smtp.gmail.com
port           587
from           $DEST
user           $DEST
password       $PW

account default : gmail
EOF
chmod 600 /etc/msmtprc
unset PW
echo "✓ Salvata in /etc/msmtprc (solo root puo' leggerla)"
echo ""

echo "Invio un messaggio di prova…"
if printf "Subject: Photocarcifo — prova\nFrom: %s\nTo: %s\n\nSe leggi questo, l'invio funziona.\nDa lunedi' riceverai il rapporto settimanale con la mappa allegata.\n" "$DEST" "$DEST" | msmtp "$DEST" 2>/tmp/errore-posta; then
    echo "✓ Inviato: controlla la posta, anche nello spam"
else
    echo "✗ Invio non riuscito:"
    cat /tmp/errore-posta
    echo ""
    echo "Cause piu' probabili:"
    echo "  · password per le app sbagliata"
    echo "  · verifica in due passaggi non attiva sull'account Google"
    exit 1
fi

"/opt/photocarcifo/venv/bin/pip" install --quiet reportlab 2>/dev/null
systemctl daemon-reload
systemctl enable --now photocarcifo-rapporto.timer 2>/dev/null

echo ""
echo "═══════════════════════════════════════════════"
echo "Ogni lunedi' alle 08:00 ricevi il rapporto."
echo ""
echo "  photocarcifo-rapporto.sh   per riceverlo subito"
echo "═══════════════════════════════════════════════"
