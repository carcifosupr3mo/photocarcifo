#!/bin/bash
# Avvisa su Telegram quando delle pagine vanno in errore, anche se il sito
# nel complesso funziona.
#
# La sentinella guarda solo se il sito risponde. Ma un album rotto, una
# miniatura che non si genera o una interrogazione al database che fallisce
# lasciano il sito "su": il controllo resta tranquillo e nessuno se ne
# accorge. Senza modulo di contatto il visitatore non ha nemmeno modo di
# segnalarlo, quindi l'unico che puo' accorgersene e' il server stesso.
#
# nginx scrive le sole risposte 5xx in un registro a parte
# (photocarcifo-5xx.log, quasi sempre vuoto). Qui si contano quelle
# dell'ultima ora.
#
# Perche' si guarda un'ora intera e non "quello che e' comparso dall'ultimo
# controllo": un guasto che produce tre errori ogni quarto d'ora non
# supererebbe mai la soglia guardando un quarto d'ora per volta, pur
# facendone quasi trecento al giorno. Contando su una finestra piu' larga
# viene fuori.
#
# Perche' una soglia e non un avviso a ogni errore: riavviare il sito per un
# aggiornamento produce qualche 502 di pochi secondi, del tutto normale. Un
# guasto vero ne produce molti di piu' e non smette da solo.

set -uo pipefail
export LC_ALL=C          # i nomi dei mesi nel registro sono in inglese

CONFIG=/etc/photocarcifo-telegram.conf
REGISTRO=/var/log/nginx/photocarcifo-5xx.log
ULTIMO=/var/lib/photocarcifo/errori.ultimo-avviso
FINESTRA=60           # minuti da guardare all'indietro
SOGLIA=5              # errori nella finestra perche' valga la pena avvisare
SILENZIO=21600        # secondi di pausa fra un avviso e il successivo (6 ore)

[ -r "$CONFIG" ] || exit 0
# shellcheck source=/dev/null
. "$CONFIG"
[ -n "${TELEGRAM_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT:-}" ] || exit 0
[ -s "$REGISTRO" ] || exit 0          # file assente o vuoto: tutto bene

mkdir -p "$(dirname "$ULTIMO")"

# ---------- le righe dell'ultima ora ----------
# nginx scrive l'orario cosi': [17/Aug/2026:08:41:03 +0200]. Invece di
# convertire la data di ogni riga si costruisce l'elenco dei minuti
# accettabili e si cercano quelli: un solo passaggio sul file.
minuti=""
for m in $(seq 0 "$FINESTRA"); do
    minuti="$minuti|$(date -d "-$m minutes" '+%d/%b/%Y:%H:%M')"
done
minuti=${minuti#|}

recenti=$(grep -E "\[(${minuti})" "$REGISTRO" 2>/dev/null | tail -n 3000)
quanti=$(printf '%s' "$recenti" | grep -c . || true)
[ "${quanti:-0}" -ge "$SOGLIA" ] || exit 0

# ---------- non ripetersi ----------
adesso=$(date +%s)
scorso=$(cat "$ULTIMO" 2>/dev/null || echo 0)
if [ $((adesso - scorso)) -lt "$SILENZIO" ]; then
    exit 0
fi
echo "$adesso" > "$ULTIMO"

# ---------- che cosa e' rotto ----------
# Dal registro in formato "main": il campo fra virgolette e' la richiesta
# ("GET /n/bmx HTTP/2.0") e subito dopo viene il codice di risposta.
dettaglio=$(printf '%s\n' "$recenti" \
    | awk -F'"' '{split($2, r, " "); split($3, s, " "); print s[1], r[2]}' \
    | sort | uniq -c | sort -rn | head -5 \
    | awk '{printf "  %s volte  %s  %s\n", $1, $2, $3}')

quando=$(date '+%d/%m/%Y alle %H:%M')

curl -s -m 20 -o /dev/null \
    --data-urlencode "chat_id=${TELEGRAM_CHAT}" \
    --data-urlencode "text=⚠️ <b>Pagine in errore su photocarcifo.ch</b>
$quanti risposte di errore nell'ultima ora, rilevate il $quando.
Il sito nel complesso risponde: sono singole pagine.

<pre>$dettaglio</pre>
Prossimo avviso non prima di 6 ore." \
    --data "parse_mode=HTML" \
    "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage"
