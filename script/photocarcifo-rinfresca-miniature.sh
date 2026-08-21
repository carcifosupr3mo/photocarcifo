#!/bin/bash
# Toglie un blocco di miniature vecchie, per farle rinascere aggiornate.
#
# Dal 17/08/2026 ogni copia generata dal sito porta dentro autore e diritti
# (vedi app/thumbnails.py). Le miniature gia' in cache sono nate prima e ne
# sono prive: sono immagini anonime, e chi le ritrova in giro non ha modo di
# sapere di chi siano.
#
# Rigenerarle tutte in una volta vorrebbe dire ore di calcolo e il doppio
# dello spazio, per tenere insieme le vecchie e le nuove. Se ne cancella
# invece un blocco per volta: sono solo copie, e subito dopo il
# pregeneratore le rifa' con la firma dentro.
#
# Gira come primo passo del pregeneratore, non a meta' notte per conto suo:
# cancellare alle 04:30 quello che verrebbe rifatto solo all'01:00 della
# notte seguente vorrebbe dire lasciare un giorno intero di miniature da
# rigenerare addosso ai visitatori.
#
# Si spegne da solo: quando non resta piu' niente di anteriore a quella
# data, non trova nulla e non c'e' altro da fare.

set -uo pipefail

CACHE=/opt/photocarcifo/data/cache/thumbnails
DATA_FIRMA='2026-08-17'
QUANTE=10000

[ -d "$CACHE" ] || exit 0

# Le miniature nascono con il nome provvisorio ".tmp" e lo cambiano solo a
# scrittura finita. Se il contenitore viene spento a meta' di una scrittura,
# quel file resta li' per sempre: non lo serve nessuno e nessuno lo ripulisce.
# Si tolgono quelli fermi da piu' di un'ora, cioe' sicuramente abbandonati.
find "$CACHE" -name '*.tmp' -mmin +60 -delete 2>/dev/null

VECCHIE=$(find "$CACHE" -type f \( -name '*.jpg' -o -name '*.webp' -o -name '*.avif' \) \
               ! -newermt "$DATA_FIRMA" 2>/dev/null | head -"$QUANTE")
QUANTI=$(printf '%s\n' "$VECCHIE" | grep -c . || true)
[ "${QUANTI:-0}" -gt 0 ] || exit 0

printf '%s\n' "$VECCHIE" | xargs -r rm -f
RESTANO=$(find "$CACHE" -type f \( -name '*.jpg' -o -name '*.webp' -o -name '*.avif' \) \
               ! -newermt "$DATA_FIRMA" 2>/dev/null | wc -l)
echo "Miniature senza firma: $QUANTI rimosse, ne restano $RESTANO"
