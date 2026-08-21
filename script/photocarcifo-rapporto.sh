#!/usr/bin/env bash
# Rapporto settimanale: cosa e' cambiato, come sta il sito, mappa in PDF.
set -uo pipefail
APP=/opt/photocarcifo
STATO="$APP/.stato-settimanale"
DEST=nathan.pollini.198@gmail.com
OGGI=$(date '+%d/%m/%Y')
CORPO=/tmp/rapporto.txt
PDF="$APP/MAPPA/Photocarcifo-Mappa.pdf"

mkdir -p "$STATO"

istantanea(){
  find "$APP/app" -type f \
    \( -name '*.py' -o -name '*.html' -o -name '*.js' -o -name '*.css' \) \
    -not -path '*__pycache__*' -printf '%P ' -exec md5sum {} \; 2>/dev/null \
    | awk '{print $1" "$2}' | sort
}

istantanea > "$STATO/attuale.txt"
[ -f "$STATO/precedente.txt" ] || cp "$STATO/attuale.txt" "$STATO/precedente.txt"

CAMBI=$(python3 - "$STATO/precedente.txt" "$STATO/attuale.txt" << 'PYEOF'
import sys

def leggi(p):
    d = {}
    for r in open(p):
        parti = r.split(None, 1)
        if len(parti) == 2:
            d[parti[0]] = parti[1].strip()
    return d

pre, att = leggi(sys.argv[1]), leggi(sys.argv[2])
nuovi = sorted(f for f in att if f not in pre)
tolti = sorted(f for f in pre if f not in att)
mod = sorted(f for f in att if f in pre and att[f] != pre[f])

righe = []
if nuovi:
    righe.append("FILE NUOVI (%d)" % len(nuovi))
    righe += ["   + " + f for f in nuovi]
    righe.append("")
if mod:
    righe.append("FILE MODIFICATI (%d)" % len(mod))
    righe += ["   ~ " + f for f in mod]
    righe.append("")
if tolti:
    righe.append("FILE RIMOSSI (%d)" % len(tolti))
    righe += ["   - " + f for f in tolti]
    righe.append("")
if not righe:
    righe.append("Nessuna modifica al programma questa settimana.")
print("\n".join(righe))
PYEOF
)

MODIFICATO=0
echo "$CAMBI" | grep -q "Nessuna modifica" || MODIFICATO=1

q(){ sqlite3 "$APP/data/photocarcifo.db" "$1" 2>/dev/null; }
FOTO=$(q "SELECT COUNT(*) FROM media;")
ALBUM=$(q "SELECT COUNT(*) FROM nodes;")
PRIV=$(q "SELECT COUNT(*) FROM nodes WHERE is_private=1;")
VISITE=$(q "SELECT COUNT(*) FROM stats WHERE event='view_node' AND ts > datetime('now','-7 days');")
DOWN=$(q "SELECT COUNT(*) FROM stats WHERE event IN ('download','zip_node','zip_select') AND ts > datetime('now','-7 days');")
PREF=$(q "SELECT COUNT(*) FROM preferiti;")
PREFSETT=$(q "SELECT COUNT(*) FROM preferiti WHERE ts > datetime('now','-7 days');")
CLIENTI=$(q "SELECT COUNT(DISTINCT ospite) FROM preferiti;")
SCADUTI=$(q "SELECT COUNT(*) FROM nodes WHERE expires_at IS NOT NULL AND expires_at < datetime('now');")
INSCAD=$(q "SELECT COUNT(*) FROM nodes WHERE expires_at IS NOT NULL AND expires_at BETWEEN datetime('now') AND datetime('now','+14 days');")
TOPALBUM=$(q "SELECT n.title || '  (' || COUNT(*) || ')' FROM stats s JOIN nodes n ON n.slug=s.ref WHERE s.event='view_node' AND s.ts > datetime('now','-7 days') GROUP BY s.ref ORDER BY COUNT(*) DESC LIMIT 5;")

LIBERO=$(df -h / | awk 'NR==2{print $4}')
USATO=$(df -h / | awk 'NR==2{print $5}')
MINI=$(find "$APP/data/cache/thumbnails" -name '*.jpg' 2>/dev/null | wc -l)
SITO=$(systemctl is-active photocarcifo)
CODICE=$(curl -sk -o /dev/null -m 15 -w '%{http_code}' https://photocarcifo.ch/ 2>/dev/null)
CERT=$(certbot certificates 2>/dev/null | grep -oP 'VALID: \K[0-9]+ days' | head -1)
COPIE=$(ls -1 "$APP/backup/aggiornamenti"/prima-aggiornamento-*.tar.gz 2>/dev/null | grep -vc extra)
CESTINO=$(find /mnt/magazzino-rw/_CESTINO -type f 2>/dev/null | wc -l)

{
echo "PHOTOCARCIFO - rapporto settimanale del $OGGI"
echo "==============================================="
echo ""
echo "COME STA IL SITO"
echo "   stato               $SITO"
echo "   risposta            $CODICE"
echo "   spazio libero       $LIBERO  (usato $USATO)"
echo "   certificato scade   ${CERT:-da verificare}"
echo "   copie disponibili   $COPIE"
echo ""
echo "ARCHIVIO"
echo "   fotografie          $FOTO"
echo "   album               $ALBUM  (di cui riservati $PRIV)"
echo "   miniature pronte    $MINI"
echo ""
echo "QUESTA SETTIMANA"
echo "   album aperti        $VISITE"
echo "   scaricamenti        $DOWN"
echo "   nuovi preferiti     $PREFSETT"
echo "   preferiti totali    $PREF  da $CLIENTI clienti"
echo ""
if [ -n "$TOPALBUM" ]; then
  echo "ALBUM PIU' VISTI"
  echo "$TOPALBUM" | sed 's/^/   /'
  echo ""
fi
if [ "${INSCAD:-0}" -gt 0 ] || [ "${SCADUTI:-0}" -gt 0 ]; then
  echo "COLLEGAMENTI RISERVATI"
  [ "${INSCAD:-0}" -gt 0 ] && echo "   $INSCAD in scadenza entro due settimane"
  [ "${SCADUTI:-0}" -gt 0 ] && echo "   $SCADUTI gia' scaduti"
  echo ""
fi
[ "${CESTINO:-0}" -gt 0 ] && { echo "CESTINO"; echo "   $CESTINO file in attesa"; echo ""; }
echo "MODIFICHE AL PROGRAMMA"
echo "$CAMBI" | sed 's/^/   /'
echo ""
echo "==============================================="
echo "In allegato la mappa aggiornata del sito."
echo ""
echo "Comandi utili:"
echo "   photocarcifo-diagnosi.sh   verifica che tutto funzioni"
echo "   mappacerca PAROLA          trova un file"
echo "   tail -50 /var/log/photocarcifo-notte.log"
} > "$CORPO"

/usr/local/bin/photocarcifo-mappa.sh >/dev/null 2>&1
"$APP/venv/bin/python" /usr/local/bin/photocarcifo-mappa-pdf.py >/dev/null 2>&1

OGGETTO="Photocarcifo - rapporto del $OGGI"
[ "$MODIFICATO" = "1" ] && OGGETTO="$OGGETTO (modifiche al programma)"
[ "$CODICE" != "200" ] && OGGETTO="ATTENZIONE - $OGGETTO"

if [ -f "$PDF" ]; then
    python3 - "$DEST" "$OGGETTO" "$CORPO" "$PDF" << 'PYEOF'
import sys, subprocess
from email.message import EmailMessage

dest, oggetto, corpo, allegato = sys.argv[1:5]
m = EmailMessage()
m["To"] = dest
m["From"] = dest
m["Subject"] = oggetto
m.set_content(open(corpo, encoding="utf-8").read())
with open(allegato, "rb") as f:
    m.add_attachment(f.read(), maintype="application", subtype="pdf",
                     filename="Photocarcifo-Mappa.pdf")
subprocess.run(["msmtp", dest], input=m.as_bytes(), check=False)
PYEOF
    echo "Rapporto inviato con la mappa allegata."
else
    msmtp "$DEST" << EOF2
Subject: $OGGETTO
To: $DEST
From: $DEST

$(cat "$CORPO")
EOF2
    echo "Rapporto inviato senza allegato."
fi

cp "$STATO/attuale.txt" "$STATO/precedente.txt"
