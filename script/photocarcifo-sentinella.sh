#!/bin/bash
# Controlla che il sito risponda e avvisa su Telegram solo se qualcosa non va.
#
# Gira ogni pochi minuti. Se il sito risponde regolarmente non scrive nulla e
# non manda niente: nessun rumore. Manda un messaggio in due soli casi,
# quando lo stato cambia:
#
#   - il sito era su e adesso e' giu'      -> avviso
#   - il sito era giu' e adesso e' tornato -> tutto a posto, con la durata
#
# Senza il ricordo dello stato precedente arriverebbe un messaggio ogni
# controllo per tutto il tempo del guasto: dopo il terzo si smette di
# leggerli, ed e' come non averli.
#
# Un solo controllo fallito non basta: potrebbe essere un riavvio o un
# singhiozzo della rete. Si riprova, e solo se cade piu' volte di fila si
# considera un guasto vero.

set -uo pipefail

CONFIG=/etc/photocarcifo-telegram.conf
INDIRIZZO="https://photocarcifo.ch/healthz"
STATO=/var/lib/photocarcifo/sentinella.stato
TENTATIVI=3           # quante prove prima di dichiarare il guasto
PAUSA=10              # secondi fra una prova e l'altra
ATTESA_MAX=15         # secondi concessi a ogni risposta

[ -r "$CONFIG" ] || exit 0            # non configurato: non fa nulla
# shellcheck source=/dev/null
. "$CONFIG"
[ -n "${TELEGRAM_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT:-}" ] || exit 0

mkdir -p "$(dirname "$STATO")"

avvisa() {
    curl -s -m 20 -o /dev/null \
        --data-urlencode "chat_id=${TELEGRAM_CHAT}" \
        --data-urlencode "text=$1" \
        --data "parse_mode=HTML" \
        "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage"
}

# ---------- il controllo ----------
vivo=0
for _ in $(seq 1 "$TENTATIVI"); do
    # curl scrive gia' 000 da solo quando non riesce a collegarsi: un
    # "|| echo 000" in coda finirebbe per accodarne un secondo e nel
    # messaggio comparirebbe "000000".
    codice=$(curl -s -o /dev/null -w "%{http_code}" -m "$ATTESA_MAX" "$INDIRIZZO" 2>/dev/null)
    codice=${codice:-000}
    if [ "$codice" = "200" ]; then vivo=1; break; fi
    sleep "$PAUSA"
done

prima=$(cat "$STATO" 2>/dev/null || echo "su")
adesso=$([ "$vivo" = 1 ] && echo "su" || echo "giu")
[ "$prima" = "$adesso" ] && exit 0     # niente di nuovo: silenzio

quando=$(date '+%d/%m/%Y alle %H:%M')

if [ "$adesso" = "giu" ]; then
    date +%s > "${STATO}.da"
    dettaglio=$([ "$codice" = "000" ] && echo "non risponde affatto" \
                                     || echo "risponde $codice")
    avvisa "🔴 <b>photocarcifo.ch non funziona</b>
Il sito $dettaglio.
Rilevato il $quando dopo $TENTATIVI controlli falliti."
else
    da=$(cat "${STATO}.da" 2>/dev/null || echo "")
    durata=""
    if [ -n "$da" ]; then
        minuti=$(( ( $(date +%s) - da ) / 60 ))
        durata="
È rimasto giù circa $minuti minuti."
    fi
    avvisa "🟢 <b>photocarcifo.ch è tornato</b>
Ripristinato il $quando.$durata"
    rm -f "${STATO}.da"
fi

echo "$adesso" > "$STATO"
