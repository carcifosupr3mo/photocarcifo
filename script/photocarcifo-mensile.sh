#!/usr/bin/env bash
# Controllo mensile: salute generale e sicurezza, non coperte dai controlli
# frequenti (photocarcifo-monitor.py ogni 5 minuti gia' guarda sito/DB/
# disco/RAM in tempo reale; questo guarda cose che cambiano lentamente e
# un controllo ogni 5 minuti non avrebbe senso su di loro).
#
# Nato il 31/08/2026, richiesto esplicitamente perche' non esisteva un
# controllo periodico su: il rinnovo automatico del certificato SSL
# funziona davvero (non solo "quando scade", ma "il rinnovo e' successo
# di recente" — un rinnovo silenziosamente rotto lo si scopre solo
# guardando la data dell'ultimo successo, non la scadenza finale),
# aggiornamenti di sicurezza del sistema in attesa, spazio disco in
# trend (non solo la soglia istantanea che gia' controlla monitor.py),
# l'archivio Synology raggiungibile, permessi/privacy degli album (come
# photocarcifo-diagnosi.sh ma automatico invece che a mano).
#
# Manda un avviso Telegram SOLO se c'e' qualcosa da guardare: un
# controllo mensile che scrive sempre "tutto ok" si legge le prime due
# volte e poi si ignora — lo stesso principio gia' in uso in
# photocarcifo-sentinella.sh/monitor.py.
set -uo pipefail
APP=/opt/photocarcifo
CONFIG=/etc/photocarcifo-telegram.conf
OGGI=$(date '+%d/%m/%Y')

[ -r "$CONFIG" ] || { echo "Telegram non configurato ($CONFIG assente), controllo non inviato" >&2; exit 0; }
# shellcheck source=/dev/null
. "$CONFIG"
if [ -z "${TELEGRAM_TOKEN:-}" ] || [ -z "${TELEGRAM_CHAT:-}" ]; then
    echo "Telegram non configurato (token/chat mancanti), controllo non inviato" >&2
    exit 0
fi

ATTENZIONI=""
aggiungi() { ATTENZIONI="${ATTENZIONI}   $1\n"; }

# --- 1. certificati SSL: non solo la scadenza, anche l'ultimo rinnovo ---
# Il rinnovo (certbot.timer, due volte al giorno) e' gia' automatico:
# qui si verifica che stia davvero succedendo, non lo si rifa'.
#
# Sono DUE certificati distinti su questo server (photocarcifo.ch e
# pannello.photocarcifo.ch), ognuno col proprio "Certificate Name": vanno
# controllati uno per uno, non insieme — un grep unico su "photocarcifo.ch"
# li confonde entrambi (il nome del secondo lo contiene come sottostringa)
# e mischia i due valori "VALID: N days" in un conteggio senza senso.
CERT_OUTPUT=$(certbot certificates 2>/dev/null)
while IFS= read -r NOME; do
    [ -n "$NOME" ] || continue
    BLOCCO=$(echo "$CERT_OUTPUT" | awk -v n="Certificate Name: $NOME" \
        '$0 ~ n{f=1} f{print} f && /^  Certificate Name:/ && $0 !~ n{exit}')
    GIORNI=$(echo "$BLOCCO" | grep -oP 'VALID: \K[0-9]+(?= days)')
    if [ -z "$GIORNI" ]; then
        aggiungi "🔒 impossibile leggere lo stato del certificato $NOME — verificare a mano"
    elif [ "$GIORNI" -lt 20 ]; then
        aggiungi "🔒 certificato $NOME scade fra $GIORNI giorni — il rinnovo automatico non sembra funzionare"
    fi
done <<< "$(echo "$CERT_OUTPUT" | grep -oP 'Certificate Name: \K.*')"

# --- 2. aggiornamenti di sicurezza del sistema ---
# "apt list --upgradable" e non "apt-get -s upgrade": il formato
# pacchetto/<repository> e' piu' semplice da riconoscere in modo
# affidabile del prefisso "Inst" (che varia leggermente fra versioni
# di apt) — qui basta cercare "-security" nel nome del repository.
SICUREZZA=$(apt list --upgradable 2>/dev/null | grep -c -- '-security')
if [ "${SICUREZZA:-0}" -gt 0 ]; then
    aggiungi "🛡️ $SICUREZZA aggiornamento/i di sicurezza disponibile/i (apt upgrade)"
fi

# --- 3. spazio disco in trend, non solo istantaneo ---
# monitor.py avvisa gia' se il disco e' quasi pieno ORA; qui si guarda se
# sta crescendo troppo in fretta, cosa che un controllo istantaneo non
# vede — confronto con la lettura del mese scorso, salvata qui.
STATO_DISCO=/var/lib/photocarcifo/mensile-disco-precedente
USATO_ORA=$(df / | awk 'NR==2{print $3}')  # in blocchi da 1K
if [ -f "$STATO_DISCO" ]; then
    USATO_PRIMA=$(cat "$STATO_DISCO")
    if [ "$USATO_PRIMA" -gt 0 ] 2>/dev/null; then
        CRESCITA_GB=$(( (USATO_ORA - USATO_PRIMA) / 1024 / 1024 ))
        if [ "$CRESCITA_GB" -ge 20 ]; then
            aggiungi "💾 disco cresciuto di ${CRESCITA_GB}GB nell'ultimo mese — verificare cosa lo riempie"
        fi
    fi
fi
echo "$USATO_ORA" > "$STATO_DISCO"

LIBERO_PERC=$(df / | awk 'NR==2{gsub("%","",$5); print $5}')
if [ "${LIBERO_PERC:-0}" -ge 85 ]; then
    LIBERO=$(df -h / | awk 'NR==2{print $4}')
    aggiungi "💾 disco al ${LIBERO_PERC}% (${LIBERO} liberi)"
fi

# --- 4. archivio Synology raggiungibile ---
mountpoint -q /mnt/magazzino || aggiungi "📁 archivio Synology (/mnt/magazzino) non risulta montato"

# --- 5. permessi/privacy degli album: stessi controlli di diagnosi.sh, ---
#        qui solo il risultato (0 attesi), non l'elenco completo.
cd "$APP" || exit 1
DB=data/photocarcifo.db
q(){ sqlite3 "$DB" "$1" 2>/dev/null; }
ORFANI=$(q 'SELECT COUNT(*) FROM media m LEFT JOIN nodes n ON n.id=m.node_id WHERE n.id IS NULL;')
SENZA_TOKEN=$(q 'SELECT COUNT(*) FROM nodes WHERE is_private=1 AND parent_id IS NOT NULL AND (access_token IS NULL OR access_token="");')
[ "${ORFANI:-0}" -gt 0 ] && aggiungi "🗂️ $ORFANI foto orfane nel database (senza album)"
[ "${SENZA_TOKEN:-0}" -gt 0 ] && aggiungi "🔑 $SENZA_TOKEN album riservato/i senza token di accesso — possibile falla di privacy"

# --- 6. automatismi systemd attesi ---
ATTESI="covers errori mensile notte numeri pregen rapporto scan sentinella"
MANCANTI=""
for a in $ATTESI; do
    systemctl is-enabled "photocarcifo-$a.timer" >/dev/null 2>&1 || MANCANTI="$MANCANTI $a"
done
[ -n "$MANCANTI" ] && aggiungi "⏱️ automatismi non attivi:$MANCANTI"

# --- messaggio: solo se c'e' qualcosa, "tutto ok" e' silenzioso ---
if [ -z "$ATTENZIONI" ]; then
    echo "Controllo mensile: tutto a posto, nessun avviso inviato."
    exit 0
fi

TESTO="🗓️ Controllo mensile Photocarcifo — $OGGI"$'\n\n'"$(printf '%b' "$ATTENZIONI")"
RISPOSTA=$(curl -s -m 20 --data-urlencode "chat_id=${TELEGRAM_CHAT}" \
    --data-urlencode "text=${TESTO}" \
    "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage")
echo "$RISPOSTA" | grep -q '"ok":true' && echo "Avviso mensile inviato." \
    || echo "ATTENZIONE: invio del controllo mensile fallito: $RISPOSTA" >&2
