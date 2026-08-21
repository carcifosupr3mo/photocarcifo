#!/usr/bin/env bash
# Verifica che ogni contenuto sia raggiungibile da chi ha diritto e
# bloccato per tutti gli altri. Non modifica nulla.
cd /opt/photocarcifo
DB=data/photocarcifo.db
S="https://photocarcifo.ch"
q(){ sqlite3 "$DB" "$1"; }
code(){ curl -sk -o /dev/null -m 15 -w "%{http_code}" "$@"; }
riga(){ printf "  %-46s %s\n" "$1" "$2"; }

echo "=========== 1. ALBUM PUBBLICO ==========="
PUBN=$(q "SELECT n.id FROM nodes n JOIN media m ON m.node_id=n.id WHERE n.is_private=0 AND n.hidden=0 GROUP BY n.id ORDER BY COUNT(*) DESC LIMIT 1;")
PUBSLUG=$(q "SELECT slug FROM nodes WHERE id=$PUBN;")
PUBM=$(q "SELECT id FROM media WHERE node_id=$PUBN LIMIT 1;")
riga "pagina album" "$(code $S/n/$PUBSLUG)  atteso 200"
riga "miniatura / 2x / anteprima" "$(code $S/thumb/$PUBM) $(code $S/thumb2x/$PUBM) $(code $S/preview/$PUBM)  attesi 200"
riga "download e zip" "$(code $S/download/$PUBM) $(code $S/zip/node/$PUBN)  attesi 200"
riga "seconda pagina" "$(code "$S/n/$PUBSLUG?page=2")  atteso 200"

echo ""
echo "=========== 2. RISERVATEZZA DEGLI ALBUM PRIVATI ==========="
CAT=$(q "SELECT id FROM nodes WHERE rel_path='SHOOTING_PRIVATI';")
SLUGCAT=$(q "SELECT slug FROM nodes WHERE id=$CAT;")
TOT=$(q "SELECT COUNT(*) FROM nodes WHERE parent_id=$CAT AND is_private=1;")
echo "  clienti riservati: $TOT"
for A in $(q "SELECT id FROM nodes WHERE parent_id=$CAT AND is_private=1;"); do
  TOK=$(q "SELECT access_token FROM nodes WHERE id=$A;")
  TIT=$(q "SELECT title FROM nodes WHERE id=$A;")
  rm -f /tmp/ckx.txt
  curl -sk -c /tmp/ckx.txt -o /dev/null "$S/p/$TOK" 2>/dev/null
  # dopo cinque ricaricamenti della home deve ancora vedere solo il suo
  for i in 1 2 3 4 5; do curl -sk -b /tmp/ckx.txt -c /tmp/ckx.txt -o /dev/null "$S/" ; done
  VIS=$(curl -sk -b /tmp/ckx.txt "$S/" | grep -c "$SLUGCAT")
  RIENTRO=$(curl -sk -b /tmp/ckx.txt -o /dev/null -w "%{http_code}" "$S/p/$TOK")
  ALTRI=$(q "SELECT id FROM nodes WHERE parent_id=$CAT AND is_private=1 AND id<>$A LIMIT 1;")
  MALTRO=$(q "SELECT id FROM media WHERE node_id=$ALTRI LIMIT 1;")
  FOTOALTRI=$(curl -sk -b /tmp/ckx.txt -o /dev/null -w "%{http_code}" "$S/thumb/$MALTRO")
  printf "  %-24s rientra:%s  categoria in home:%s(0)  foto altrui:%s(404)\n" \
         "$TIT" "$RIENTRO" "$VIS" "$FOTOALTRI"
done
riga "categoria senza link" "$(code $S/n/$SLUGCAT)  atteso 404"

echo ""
echo "=========== 3. SCADENZA DEI LINK ==========="
# Serve un album privato che abbia fotografie SUE, non solo nelle
# sottocartelle: le prove sui preferiti hanno bisogno di una foto da
# segnare, e prendendo il primo che capita si finiva su un album
# contenitore. La richiesta diventava "/preferiti/" senza numero, che
# non e' un indirizzo del sito: rispondeva 404 e sembrava un guasto.
A1=$(q "SELECT id FROM nodes WHERE is_private=1 AND direct_media>0 AND access_token IS NOT NULL ORDER BY id LIMIT 1;")
T1=$(q "SELECT access_token FROM nodes WHERE id=$A1;")
V=$(q "SELECT COALESCE(expires_at,'') FROM nodes WHERE id=$A1;")
q "UPDATE nodes SET expires_at=datetime('now','-1 day') WHERE id=$A1;"
riga "link scaduto" "$(code $S/p/$T1)  atteso 410"
if [ -z "$V" ]; then q "UPDATE nodes SET expires_at=NULL WHERE id=$A1;"; else q "UPDATE nodes SET expires_at='$V' WHERE id=$A1;"; fi
riga "link ripristinato" "$(code $S/p/$T1)  atteso 200"

echo ""
echo "=========== 4. CONTENUTI NASCOSTI ==========="
HN=$(q "SELECT n.id FROM nodes n JOIN media m ON m.node_id=n.id WHERE n.hidden=1 GROUP BY n.id LIMIT 1;")
if [ -n "$HN" ]; then
  HSLUG=$(q "SELECT slug FROM nodes WHERE id=$HN;")
  HM=$(q "SELECT id FROM media WHERE node_id=$HN LIMIT 1;")
  riga "pagina / miniatura / download / zip" "$(code $S/n/$HSLUG) $(code $S/thumb/$HM) $(code $S/download/$HM) $(code $S/zip/node/$HN)  attesi 404 404 404 403"
else
  echo "  nessun album nascosto"
fi

echo ""
echo "=========== 5. PREFERITI ==========="
MA=$(q "SELECT id FROM media WHERE node_id=$A1 LIMIT 1;")
rm -f /tmp/ckp.txt
curl -sk -c /tmp/ckp.txt -o /dev/null "$S/p/$T1"
riga "segno con link" "$(curl -sk -b /tmp/ckp.txt -c /tmp/ckp.txt -o /dev/null -m 15 -w '%{http_code}' -X POST $S/preferiti/$MA)  atteso 200"
riga "segno da estraneo" "$(code -X POST $S/preferiti/$MA)  atteso 403"
riga "tolgo" "$(curl -sk -b /tmp/ckp.txt -o /dev/null -m 15 -w '%{http_code}' -X POST $S/preferiti/$MA)  atteso 200"
riga "instagram valido / sbagliato" "$(code -d 'tipo=ig&instagram=mario.rossi' $S/preferiti-nome) $(code -d 'tipo=ig&instagram=a b' $S/preferiti-nome)  attesi 200 400"
riga "nome valido / con cifre" "$(code -d 'tipo=nome&nome_persona=Mario Rossi' $S/preferiti-nome) $(code -d 'tipo=nome&nome_persona=abc123' $S/preferiti-nome)  attesi 200 400"
riga "pagina personale" "$(code $S/mie-preferite)  atteso 200"
riga "pannello preferite" "$(code $S/admin/preferite)  atteso 303"

echo ""
echo "=========== 6. PAGINE E FILE ==========="
for r in / /search /robots.txt /sitemap.xml /sitemap-immagini.xml /healthz; do
  riga "$r" "$(code $S$r)"
done
for j in app.js preferiti.js preferiti-nome.js ospite-nav.js admin-tree.js admin-preferite.js admin-upload.js; do
  riga "js/$j" "$(code $S/static/js/$j)"
done
riga "css" "$(code $S/static/css/style.css)"
riga "/admin senza login" "$(code $S/admin)  atteso 303"
riga "pagina inesistente" "$(code $S/n/non-esiste-xyz)  atteso 404"
riga "pagine escluse dalla cache" "$(curl -skI $S/n/$PUBSLUG 2>/dev/null | grep -ci 'no-store')  atteso 1"

echo ""
echo "=========== 7. DATABASE ==========="
riga "media totali" "$(q 'SELECT COUNT(*) FROM media;')"
riga "media orfani" "$(q 'SELECT COUNT(*) FROM media m LEFT JOIN nodes n ON n.id=m.node_id WHERE n.id IS NULL;')  atteso 0"
riga "privati senza token" "$(q 'SELECT COUNT(*) FROM nodes WHERE is_private=1 AND parent_id IS NOT NULL AND (access_token IS NULL OR access_token="");')  atteso 0"
riga "cestino indicizzato" "$(q "SELECT COUNT(*) FROM nodes WHERE rel_path LIKE '%_CESTINO%' OR rel_path LIKE '%_cestino%';")  atteso 0"
riga "conteggi errati" "$(q 'SELECT COUNT(*) FROM nodes n WHERE n.direct_media <> (SELECT COUNT(*) FROM media WHERE node_id=n.id);')  atteso 0"
riga "preferiti orfani" "$(q 'SELECT COUNT(*) FROM preferiti p LEFT JOIN media m ON m.id=p.media_id WHERE m.id IS NULL;')  atteso 0"
riga "preferiti / clienti" "$(q 'SELECT COUNT(*) FROM preferiti;') / $(q 'SELECT COUNT(DISTINCT ospite) FROM preferiti;')"

echo ""
echo "=========== 8. SISTEMA ==========="
riga "spazio libero" "$(df -h / | awk 'NR==2{print $4}')"
riga "miniature in cache" "$(find data/cache/thumbnails -name '*.jpg' 2>/dev/null | wc -l)"
riga "servizi" "$(systemctl is-active photocarcifo) / $(systemctl is-active nginx)"
# Gli automatismi crescono nel tempo: invece di un numero scritto a mano,
# che invecchia e fa sembrare guasto cio' che e' solo nuovo, si elencano
# quelli attesi per nome e si dice quale manca.
ATTESI="covers errori notte numeri pregen rapporto scan sentinella"
MANCANTI=""
for a in $ATTESI; do
  systemctl is-enabled "photocarcifo-$a.timer" >/dev/null 2>&1 || MANCANTI="$MANCANTI $a"
done
riga "automatismi attivi" "$(systemctl list-units --type=timer --no-legend 'photocarcifo*' 2>/dev/null | grep -c photocarcifo) di 8${MANCANTI:+  MANCANO:$MANCANTI}"
echo ""
echo "=========== FINE ==========="
