#!/usr/bin/env bash
# Rapporto settimanale: cosa e' cambiato, come sta il sito, mappa in PDF.
#
# Passato da email a Telegram il 31/08/2026, richiesto esplicitamente per
# uniformare il canale — prima era l'unico avviso del sito ancora via
# email (msmtp), tutto il resto (ban, errori, sentinella, monitor) usa
# gia' lo stesso bot amministrativo. Stessa configurazione condivisa di
# tutti gli altri script bash del progetto (photocarcifo-sentinella.sh,
# photocarcifo-errori.sh): un "source" diretto di
# /etc/photocarcifo-telegram.conf, niente file nuovo.
set -uo pipefail
APP=/opt/photocarcifo
STATO="$APP/.stato-settimanale"
CONFIG=/etc/photocarcifo-telegram.conf
OGGI=$(date '+%d/%m/%Y')
CORPO=/tmp/rapporto.txt
PDF="$APP/MAPPA/Photocarcifo-Mappa.pdf"

[ -r "$CONFIG" ] || { echo "Telegram non configurato ($CONFIG assente), rapporto non inviato" >&2; exit 0; }
# shellcheck source=/dev/null
. "$CONFIG"
if [ -z "${TELEGRAM_TOKEN:-}" ] || [ -z "${TELEGRAM_CHAT:-}" ]; then
    echo "Telegram non configurato (token/chat mancanti), rapporto non inviato" >&2
    exit 0
fi

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
VISITE=$(q "SELECT COUNT(*) FROM stats WHERE event='view_node' AND ts > datetime('now','-7 days');")
DOWN=$(q "SELECT COUNT(*) FROM stats WHERE event IN ('download','zip_node','zip_select') AND ts > datetime('now','-7 days');")
PREF=$(q "SELECT COUNT(*) FROM preferiti;")
PREFSETT=$(q "SELECT COUNT(*) FROM preferiti WHERE ts > datetime('now','-7 days');")
CLIENTI=$(q "SELECT COUNT(DISTINCT ospite) FROM preferiti;")
SCADUTI=$(q "SELECT COUNT(*) FROM nodes WHERE expires_at IS NOT NULL AND expires_at < datetime('now');")
INSCAD=$(q "SELECT COUNT(*) FROM nodes WHERE expires_at IS NOT NULL AND expires_at BETWEEN datetime('now') AND datetime('now','+14 days');")
TOPALBUM=$(q "SELECT n.title || '  (' || COUNT(*) || ')' FROM stats s JOIN nodes n ON n.slug=s.ref WHERE s.event='view_node' AND s.ts > datetime('now','-7 days') GROUP BY s.ref ORDER BY COUNT(*) DESC LIMIT 5;")

# Solo cio' che serve per decidere se mostrare un'attenzione (vedi sotto):
# lo stato del sito e la risposta HTTP non compaiono piu' nel messaggio
# (li segnalano gia' sentinella/monitor se cambia qualcosa), ma CODICE
# resta per marcare il titolo se il sito risultasse giu' proprio ora.
LIBERO=$(df -h / | awk 'NR==2{print $4}')
CODICE=$(curl -sk -o /dev/null -m 15 -w '%{http_code}' https://photocarcifo.ch/ 2>/dev/null)
CERT=$(certbot certificates 2>/dev/null | grep -oP 'VALID: \K[0-9]+ days' | head -1)
CESTINO=$(find /mnt/magazzino-rw/_CESTINO -type f 2>/dev/null | wc -l)

# Formato rivisto il 31/08/2026: il rapporto via email aveva senso in
# colonne allineate (font monospace), su Telegram con testo semplice
# diventava una parete di numeri tecnici senza gerarchia. Qui si tiene
# solo cio' che serve leggere al volo su un messaggio: i numeri della
# settimana, gli album piu' visti, e un'attenzione SOLO quando c'e'
# davvero qualcosa da guardare (certificato quasi scaduto, poco spazio,
# link scaduti) — il resto (stato/HTTP, miniature pronte, copie di
# backup, comandi da terminale) non ha senso in un messaggio del
# telefono: se il sito fosse giu' lo si saprebbe gia' dagli altri
# avvisi (sentinella/monitor), non serve ripeterlo qui ogni settimana.
{
echo "📊 Photocarcifo — $OGGI"
echo ""
echo "👀 Questa settimana"
echo "   $VISITE album aperti · $DOWN scaricamenti"
if [ "${PREFSETT:-0}" -gt 0 ]; then
  echo "   $PREFSETT nuovi preferiti (totale $PREF da $CLIENTI clienti)"
fi
if [ -n "$TOPALBUM" ]; then
  echo ""
  echo "🏆 Più visti"
  echo "$TOPALBUM" | sed 's/^/   /'
fi

ATTENZIONI=""
if [ -n "${CERT:-}" ] && [ "$CERT" -lt 20 ] 2>/dev/null; then
  ATTENZIONI="${ATTENZIONI}   🔒 certificato SSL scade fra $CERT giorni — verificare il rinnovo automatico\n"
fi
LIBERO_PERC=$(df / | awk 'NR==2{gsub("%","",$5); print $5}')
if [ "${LIBERO_PERC:-0}" -ge 85 ]; then
  ATTENZIONI="${ATTENZIONI}   💾 disco al ${LIBERO_PERC}% (${LIBERO} liberi)\n"
fi
if [ "${SCADUTI:-0}" -gt 0 ]; then
  ATTENZIONI="${ATTENZIONI}   🔗 $SCADUTI collegamento/i riservato/i già scaduto/i\n"
fi
if [ "${INSCAD:-0}" -gt 0 ]; then
  ATTENZIONI="${ATTENZIONI}   🔗 $INSCAD collegamento/i riservato/i in scadenza entro due settimane\n"
fi
if [ "${CESTINO:-0}" -gt 20 ]; then
  ATTENZIONI="${ATTENZIONI}   🗑️ $CESTINO file in attesa nel cestino\n"
fi
if [ "$MODIFICATO" = "1" ]; then
  ATTENZIONI="${ATTENZIONI}   🛠️ modifiche al codice questa settimana (vedi photocarcifo-diagnosi.sh)\n"
fi
if [ -n "$ATTENZIONI" ]; then
  echo ""
  echo "⚠️ Da guardare"
  printf '%b' "$ATTENZIONI"
fi
} > "$CORPO"

/usr/local/bin/photocarcifo-mappa.sh >/dev/null 2>&1
"$APP/venv/bin/python" /usr/local/bin/photocarcifo-mappa-pdf.py >/dev/null 2>&1

TITOLO="📊 Photocarcifo - rapporto del $OGGI"
[ "$MODIFICATO" = "1" ] && TITOLO="$TITOLO (modifiche al programma)"
[ "$CODICE" != "200" ] && TITOLO="⚠️ ATTENZIONE - $TITOLO"

# Un messaggio Telegram supera i 4096 caratteri raramente con questo
# rapporto, ma "modifiche al programma" con molti file puo' avvicinarcisi:
# si taglia con un avviso invece di far fallire l'invio in silenzio (vedi
# lo stesso problema, gia' capitato per davvero, in ban-alert.py).
LIMITE_TELEGRAM=3900
TESTO="$TITOLO"$'\n\n'"$(cat "$CORPO")"
if [ "${#TESTO}" -gt "$LIMITE_TELEGRAM" ]; then
    TESTO="${TESTO:0:$LIMITE_TELEGRAM}"$'\n\n[…troncato, il rapporto completo era piu lungo del limite di Telegram]'
fi

RISPOSTA=$(curl -s -m 20 --data-urlencode "chat_id=${TELEGRAM_CHAT}" \
    --data-urlencode "text=${TESTO}" \
    "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage")
echo "$RISPOSTA" | grep -q '"ok":true' && echo "Rapporto inviato su Telegram." \
    || echo "ATTENZIONE: invio del rapporto su Telegram fallito: $RISPOSTA" >&2

if [ -f "$PDF" ]; then
    RISPOSTA_PDF=$(curl -s -m 60 -F "chat_id=${TELEGRAM_CHAT}" \
        -F "document=@${PDF};filename=Photocarcifo-Mappa.pdf" \
        -F "caption=Mappa aggiornata del sito" \
        "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendDocument")
    echo "$RISPOSTA_PDF" | grep -q '"ok":true' && echo "Mappa inviata come documento." \
        || echo "ATTENZIONE: invio della mappa su Telegram fallito: $RISPOSTA_PDF" >&2
else
    echo "Mappa PDF non trovata ($PDF), rapporto inviato senza."
fi

cp "$STATO/attuale.txt" "$STATO/precedente.txt"
