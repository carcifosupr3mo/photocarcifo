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

passo "I permessi di .env"
# Il 01/09/2026 un salvataggio di .env lo ha lasciato di proprieta' di root
# invece che di photocarcifo: il servizio (che gira come utente
# photocarcifo, vedi deploy/photocarcifo.service) non riusciva piu' a
# leggerlo, e il sito e' rimasto giu' (502) dal riavvio successivo finche'
# qualcuno non se n'e' accorto da journalctl. Controllo qui, PRIMA del
# riavvio: se serve una correzione la si fa subito (chown/chmod, la stessa
# operazione fatta a mano quel giorno — coerente con questo script, che
# gia' gira con i privilegi per riavviare il servizio), cosi' un domani lo
# stesso errore non arriva mai a diventare un sito giu'. Il contenuto del
# file non viene mai stampato, solo owner e permessi.
if [ -f .env ]; then
    proprietario_attuale=$(stat -c '%U:%G' .env)
    permessi_attuali=$(stat -c '%a' .env)
    disallineato=0
    [ "$proprietario_attuale" != "photocarcifo:photocarcifo" ] || [ "$permessi_attuali" != "600" ] && disallineato=1
    if [ "$disallineato" = 1 ]; then
        if [ "$SOLO_PROVA" = 1 ]; then
            # --prova non deve toccare nulla, nemmeno questo: solo
            # segnalare cosa correggerebbe il deploy vero.
            ko ".env e' $proprietario_attuale $permessi_attuali (atteso photocarcifo:photocarcifo 600) — il deploy vero lo correggerebbe qui"
        fi
        printf '  ! .env e'"'"' %s %s (atteso photocarcifo:photocarcifo 600), corretto\n' \
               "$proprietario_attuale" "$permessi_attuali"
        chown photocarcifo:photocarcifo .env 2>/tmp/env-perm.out \
            && chmod 600 .env 2>>/tmp/env-perm.out \
            || { sed 's/^/    /' /tmp/env-perm.out; ko "correzione permessi .env fallita"; }
    fi
    # Non ci si fida solo di aver appena impostato i bit giusti: si
    # verifica che l'utente del servizio legga DAVVERO il file, con lo
    # stesso controllo che ha fermato il riavvio quel giorno (vedi sopra).
    # In --prova questo punto si raggiunge solo se era gia' tutto a posto.
    if ! su photocarcifo -s /bin/sh -c 'test -r .env' 2>/dev/null; then
        ko ".env non leggibile dall'utente photocarcifo anche dopo la correzione"
    fi
    ok "photocarcifo:photocarcifo 600, leggibile dal servizio"
else
    ok ".env assente, niente da controllare"
fi

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
