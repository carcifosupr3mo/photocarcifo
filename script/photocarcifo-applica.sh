#!/bin/bash
# Mette in servizio le modifiche al sito, controllando prima che reggano.
#
# Esiste per un errore preciso. Il 17/08/2026 un modello di pagina e' stato
# modificato per usare una funzione che il processo in esecuzione non
# conosceva ancora: i modelli si rileggono dal disco a ogni richiesta, il
# codice solo al riavvio. Per i secondi fra le due cose ogni pagina del
# sito ha risposto "errore interno", e in quella finestra e' passato
# Googlebot.
#
# Qui i controlli vengono prima e il riavvio dopo. Se qualcosa non torna,
# il sito resta com'era: continua a servire la versione che funziona.
#
#   photocarcifo-applica.sh            controlla, riavvia, verifica
#   photocarcifo-applica.sh --prova    controlla soltanto, non tocca nulla

set -uo pipefail

APP=/opt/photocarcifo
PY="$APP/venv/bin/python"
SOLO_PROVA=0
[ "${1:-}" = "--prova" ] && SOLO_PROVA=1

cd "$APP" || { echo "✗ cartella $APP non trovata"; exit 1; }

passo() { printf '\n▸ %s\n' "$1"; }
ok()    { printf '  ✓ %s\n' "$1"; }
ko()    { printf '  ✗ %s\n' "$1"; exit 1; }

passo "Il codice si legge"
$PY -m compileall -q app > /dev/null 2>&1 || ko "ci sono errori di sintassi"
ok "sintassi a posto"

passo "Nessun avanzo nel codice"
if $PY -m pyflakes app/ > /tmp/pyflakes.out 2>&1; then
    ok "niente import o variabili inutilizzate"
else
    sed 's/^/    /' /tmp/pyflakes.out
    ko "segnalazioni da sistemare"
fi

passo "Il JavaScript si legge"
# Una parentesi dimenticata in un file di script non da' nessun errore sul
# server: la pagina esce regolarmente e la funzione semplicemente non parte.
# Il pulsante resta li' a non fare niente, e lo si scopre solo usandolo.
if command -v node > /dev/null 2>&1; then
    guasti_js=0
    for f in app/static/js/*.js; do
        node --check "$f" 2>/tmp/node.out || { printf '    %s\n' "$f"; sed 's/^/      /' /tmp/node.out; guasti_js=1; }
    done
    [ "$guasti_js" = 0 ] || ko "errori di sintassi nel JavaScript"
    ok "$(ls app/static/js/*.js | wc -l) file a posto"
else
    ok "node non installato: controllo saltato"
fi

passo "L'applicazione si carica"
$PY -c "import app.main" 2>/tmp/import.out || { sed 's/^/    /' /tmp/import.out; ko "non si carica"; }
ok "moduli e rotte a posto"

passo "I test"
if $PY -m pytest tests -q > /tmp/pytest.out 2>&1; then
    ok "$(tail -1 /tmp/pytest.out)"
else
    tail -25 /tmp/pytest.out | sed 's/^/    /'
    ko "test falliti: il sito NON e' stato toccato"
fi

passo "La configurazione di nginx"
nginx -t > /dev/null 2>&1 || { nginx -t 2>&1 | sed 's/^/    /'; ko "configurazione non valida"; }
ok "configurazione valida"

if [ "$SOLO_PROVA" = 1 ]; then
    printf '\nSolo prova: tutto a posto, niente e" stato riavviato.\n'
    exit 0
fi

passo "Riavvio"
systemctl reload nginx
systemctl restart photocarcifo
# Si aspetta che risponda davvero, invece di dare per buono il riavvio.
for _ in $(seq 30); do
    sleep 1
    [ "$(curl -s -o /dev/null -m 3 -w '%{http_code}' http://127.0.0.1:8000/healthz)" = "200" ] && break
done

passo "Verifica dal vivo"
guasti=0
for indirizzo in / /n/bmx /novita /chi-sono /recensioni /privacy /en/ /fr/n/bmx \
                 /robots.txt /sitemap.xml /novita.xml /healthz; do
    codice=$(curl -s -o /dev/null -m 10 -w '%{http_code}' \
             -H 'Accept: text/html' "https://photocarcifo.ch$indirizzo")
    if [ "$codice" != "200" ]; then
        printf '  ✗ %s -> %s\n' "$indirizzo" "$codice"
        guasti=$((guasti + 1))
    fi
done
[ "$guasti" -eq 0 ] || ko "$guasti pagine non rispondono: guarda journalctl -u photocarcifo"
ok "12 indirizzi su 12 rispondono"

printf '\nFatto. Il sito e" in servizio con le modifiche.\n'
