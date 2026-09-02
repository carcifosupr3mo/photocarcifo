#!/bin/bash
# Da lanciare a mano dopo aver caricato foto nuove sul Synology.
#
# I tre passi (scansione, miniature, numeri) girano gia' da soli sui loro
# timer, ma con un intervallo di minuti o solo di notte: chi ha appena
# caricato un servizio e vuole vederlo pronto subito non deve aspettare il
# giro. Questo script fa la stessa sequenza, subito, in un colpo solo.
#
#   photocarcifo-aggiunta-foto.sh            scansione + miniature + numeri
#   photocarcifo-aggiunta-foto.sh --no-numeri   salta la lettura dei numeri
#
# Ogni passo e' gia' sicuro se lanciato mentre un altro giro (timer o
# pannello) sta facendo la stessa cosa: la scansione e le miniature
# lavorano sempre sul database, i numeri hanno un lucchetto proprio e si
# limitano a segnalarlo invece di sommarsi.

set -uo pipefail

APP=/opt/photocarcifo
PY="$APP/venv/bin/python"
SALTA_NUMERI=0
[ "${1:-}" = "--no-numeri" ] && SALTA_NUMERI=1

cd "$APP" || { echo "✗ cartella $APP non trovata"; exit 1; }

passo() { printf '\n▸ %s\n' "$1"; }

passo "Scansione del NAS"
if ! "$PY" -m app.cli scan; then
    echo "✗ scansione non riuscita, mi fermo qui"
    exit 1
fi

passo "Miniature del materiale nuovo"
# processi/tempo minimi: qui interessano solo le foto appena arrivate,
# poche decine o centinaia, non tutto l'archivio. Il pregeneratore
# notturno le salta gia' fatte quando arriva il suo turno.
PREGEN_MINUTI=15 "$PY" script/photocarcifo-pregen.py

if [ "$SALTA_NUMERI" = 1 ]; then
    printf '\nFatto: scansione e miniature aggiornate, numeri saltati su richiesta.\n'
    exit 0
fi

passo "Lettura dei numeri di gara"
"$PY" -m app.cli numeri --all

printf '\nFatto.\n'
