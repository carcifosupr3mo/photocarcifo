#!/usr/bin/env bash
# Ripara da solo i guasti che si sanno riparare.
#
# Non e' un "aggiusta tutto": e' un elenco chiuso di sintomi conosciuti,
# ognuno con la sua cura, scritta qui e verificabile. Cio' che non e' in
# questo elenco viene segnalato e basta.
#
# Il confine e' netto e voluto. Questo script puo':
#   - riaccendere un servizio spento
#   - rimontare l'archivio
#   - dare un link a un album privato che non ce l'ha
#   - buttare via righe di database che non servono piu' a nessuno
#   - fare spazio con registri e pacchetti scaricati
#   - riaccendere un automatismo disattivato
# Questo script NON puo':
#   - toccare il codice del sito
#   - cancellare fotografie, album o recensioni
#   - riavviare la macchina
#   - cambiare configurazioni
# Un programma che ripara da solo va tenuto stretto: il danno peggiore lo
# fa quando "aggiusta" qualcosa che andava bene.

set -uo pipefail
export LC_ALL=C

APP=/opt/photocarcifo
DB="$APP/data/photocarcifo.db"
FATTI=0
VISTI=0
SOLO_GUARDA=0
[ "${1:-}" = "--guarda" ] && SOLO_GUARDA=1

ok()    { echo "  ✓ $1"; }
trovato() { VISTI=$((VISTI+1)); echo "  ⚠ $1"; }
fatto()  { FATTI=$((FATTI+1)); echo "    → $1"; }
niente() { echo "    → da sistemare a mano: $1"; }

agisci() {
    # In modalita' "guarda" si dice cosa si farebbe, senza farlo.
    if [ "$SOLO_GUARDA" = "1" ]; then
        echo "    → (si farebbe: $1)"
        return 1
    fi
    return 0
}

echo "═══ Riparazione — $(date '+%d/%m/%Y %H:%M') ═══"
echo ""

# ---------- 1. Il sito risponde? ----------
echo "▸ Il sito risponde"
CODICE=$(curl -s -o /dev/null -m 20 -w '%{http_code}' http://127.0.0.1:8000/healthz)
if [ "$CODICE" = "200" ]; then
    ok "risponde 200"
else
    trovato "risponde $CODICE"
    if agisci "riavvio il servizio"; then
        systemctl restart photocarcifo
        sleep 8
        CODICE=$(curl -s -o /dev/null -m 20 -w '%{http_code}' http://127.0.0.1:8000/healthz)
        if [ "$CODICE" = "200" ]; then
            fatto "riavviato, adesso risponde"
        else
            niente "riavviato ma risponde ancora $CODICE"
        fi
    fi
fi

# ---------- 2. nginx ----------
echo "▸ nginx"
if nginx -t >/dev/null 2>&1; then
    if systemctl is-active --quiet nginx; then
        ok "acceso e configurazione valida"
    else
        trovato "configurazione valida ma il servizio e' spento"
        if agisci "lo riaccendo"; then
            systemctl start nginx && fatto "riacceso" || niente "non riparte"
        fi
    fi
else
    trovato "la configurazione di nginx non e' valida"
    # Qui non si tocca niente di proposito: una configurazione rotta si
    # guarda, non si indovina. Riavviare peggiorerebbe soltanto.
    niente "$(nginx -t 2>&1 | tail -1)"
fi

# ---------- 3. L'archivio delle fotografie ----------
echo "▸ Archivio"
if mountpoint -q /mnt/magazzino; then
    ok "collegato"
else
    trovato "non collegato: le fotografie non si vedono"
    if agisci "provo a rimontarlo"; then
        mount /mnt/magazzino 2>/dev/null
        if mountpoint -q /mnt/magazzino; then
            fatto "rimontato"
        else
            niente "non si rimonta: guardare il NAS e la rete"
        fi
    fi
fi

# ---------- 4. Album privati senza link ----------
# E' il guasto del 19/08/2026: un album privato senza link non lo apre
# nessuno, nemmeno chi lo possiede, e dal pannello si finiva su /p/None.
echo "▸ Album privati"
ORFANI=$("$APP/venv/bin/python" - <<'PY' 2>/dev/null
import sys
sys.path.insert(0, "/opt/photocarcifo")
from app.database import get_db
with get_db() as c:
    print(c.execute("SELECT COUNT(*) n FROM nodes WHERE is_private=1 "
                    "AND (access_token IS NULL OR access_token='')").fetchone()["n"])
PY
)
if [ "${ORFANI:-0}" = "0" ]; then
    ok "tutti hanno il loro link"
else
    trovato "$ORFANI senza link: non si possono aprire"
    if agisci "genero i link mancanti"; then
        RIPARATI=$("$APP/venv/bin/python" - <<'PY' 2>/dev/null
import sys
sys.path.insert(0, "/opt/photocarcifo")
from datetime import datetime, timezone
from app.database import get_db
from app.security import generate_access_token
ora = datetime.now(timezone.utc).isoformat()
n = 0
with get_db() as c:
    for r in c.execute("SELECT id FROM nodes WHERE is_private=1 "
                       "AND (access_token IS NULL OR access_token='')").fetchall():
        c.execute("UPDATE nodes SET access_token=?, updated_at=? WHERE id=?",
                  (generate_access_token(), ora, r["id"]))
        n += 1
print(n)
PY
)
        fatto "$RIPARATI album hanno di nuovo un link"
    fi
fi

# ---------- 5. Righe di database che non servono piu' ----------
echo "▸ Database"
SPORCO=$(sqlite3 "$DB" "
  SELECT (SELECT COUNT(*) FROM preferiti WHERE media_id NOT IN (SELECT id FROM media))
       + (SELECT COUNT(*) FROM tentativi WHERE quando < strftime('%s','now') - 86400);" 2>/dev/null)
if [ "${SPORCO:-0}" = "0" ]; then
    ok "nessuna riga da buttare"
else
    trovato "$SPORCO righe che non servono piu'"
    if agisci "le tolgo"; then
        sqlite3 "$DB" "
          DELETE FROM preferiti WHERE media_id NOT IN (SELECT id FROM media);
          DELETE FROM tentativi WHERE quando < strftime('%s','now') - 86400;
          PRAGMA optimize;" 2>/dev/null && fatto "database ripulito" \
          || niente "il database non risponde"
    fi
fi

# ---------- 6. Spazio ----------
echo "▸ Spazio"
LIBERI=$(df --output=avail -BG / | tail -1 | tr -dc '0-9')
if [ "${LIBERI:-0}" -ge 8 ]; then
    ok "${LIBERI} GB liberi"
else
    trovato "solo ${LIBERI} GB liberi"
    if agisci "svuoto registri e pacchetti scaricati"; then
        journalctl --vacuum-size=100M -q 2>/dev/null
        apt-get clean >/dev/null 2>&1
        rm -rf /tmp/app-guasta-* 2>/dev/null
        DOPO=$(df --output=avail -BG / | tail -1 | tr -dc '0-9')
        fatto "recuperati $((DOPO - LIBERI)) GB (ora ${DOPO} GB liberi)"
        [ "$DOPO" -lt 8 ] && niente "servono ancora: guardare cache e copie"
    fi
fi

# ---------- 7. Gli automatismi ----------
echo "▸ Automatismi"
ATTESI="covers errori notte numeri pregen rapporto scan sentinella"
SPENTI=""
for a in $ATTESI; do
    systemctl is-enabled "photocarcifo-$a.timer" >/dev/null 2>&1 || SPENTI="$SPENTI $a"
done
systemctl is-enabled photocarcifo-bot.service >/dev/null 2>&1 || SPENTI="$SPENTI bot"
if [ -z "$SPENTI" ]; then
    ok "tutti attivi"
else
    trovato "spenti:$SPENTI"
    if agisci "li riaccendo"; then
        for a in $SPENTI; do
            if [ "$a" = "bot" ]; then
                systemctl enable -q --now photocarcifo-bot.service 2>/dev/null
            else
                systemctl enable -q --now "photocarcifo-$a.timer" 2>/dev/null
            fi
        done
        fatto "riaccesi:$SPENTI"
    fi
fi

# ---------- 8. Le guardie ----------
# I carceri di fail2ban possono restare indietro dopo un aggiornamento o un
# riavvio, e nessuno se ne accorge: il sito continua a funzionare benissimo
# mentre chi bussa alle porte chiuse lo fa indisturbato.
echo "▸ Guardie"
CARCERI="photocarcifo-scansioni photocarcifo-login nginx-botsearch sshd"
MUTI=""
for c in $CARCERI; do
    fail2ban-client status "$c" >/dev/null 2>&1 || MUTI="$MUTI $c"
done
if [ -z "$MUTI" ]; then
    # Si somma con awk e non con bc: bc su questa macchina non c'e', e il
    # conto tornava sempre zero in silenzio.
    BLOCCATI=$(for c in $CARCERI; do
        fail2ban-client status "$c" 2>/dev/null | sed -n 's/.*Currently banned:[[:space:]]*\([0-9]*\).*/\1/p'
    done | awk '{t+=$1} END {print t+0}')
    ok "tutte in servizio (${BLOCCATI:-0} indirizzi bloccati adesso)"
else
    trovato "guardie non attive:$MUTI"
    if agisci "riavvio fail2ban"; then
        systemctl restart fail2ban
        sleep 5
        ANCORA=""
        for c in $MUTI; do
            fail2ban-client status "$c" >/dev/null 2>&1 || ANCORA="$ANCORA $c"
        done
        if [ -z "$ANCORA" ]; then
            fatto "tutte in servizio"
        else
            niente "restano ferme:$ANCORA"
        fi
    fi
fi

# ---------- 9. I controlli completi ----------
# Qui non si ripara: si guarda e si riferisce. Se una prova non torna, il
# motivo puo' essere in mille posti, e indovinare sarebbe peggio del guasto.
echo "▸ Controlli completi"
STORTI=$(/usr/local/bin/photocarcifo-diagnosi.sh 2>/dev/null | awk '
  /attes[oi]/ {
    n = split($0, a, /attes[oi]/); ott = a[1]; att = a[2];
    gsub(/[^0-9 ]/, " ", ott); gsub(/[^0-9 ]/, " ", att);
    no = split(ott, x, " "); na = split(att, y, " ");
    if (na == 0) next;
    for (i = 0; i < na; i++) if (x[no-i] != y[na-i]) { print; next }
  }')
if [ -z "$STORTI" ]; then
    ok "tutti i controlli tornano"
else
    N=$(echo "$STORTI" | wc -l)
    trovato "$N controlli non tornano"
    echo "$STORTI" | sed 's/^ */    /'
    niente "vanno guardati a mano: non sono cose da indovinare"
fi

echo ""
if [ "$SOLO_GUARDA" = "1" ]; then
    echo "═══ Trovati $VISTI problemi (nessuno toccato: era solo un'occhiata) ═══"
elif [ "$VISTI" = "0" ]; then
    echo "═══ Niente da riparare ═══"
else
    echo "═══ Trovati $VISTI problemi, riparati $FATTI ═══"
fi
