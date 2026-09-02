#!/usr/bin/env bash
# Aggiorna il repository pubblico GitHub in sicurezza.
#
#   ./git-update.sh "descrizione della modifica"
#
# Fa, in ordine, e si ferma al primo problema:
#   1. controllo di sicurezza sui file che verrebbero aggiunti
#   2. mostra esattamente cosa sta per essere committato
#   3. esegue i test essenziali
#   4. crea il commit
#   5. fa il push, solo se tutto il resto e' andato bene
#
# Non fa mai "git add -A" alla cieca, non fa mai "git push --force", non
# tocca la produzione: aggiorna solo la storia di questo repository git.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

MSG="${1:-}"
if [ -z "$MSG" ]; then
    echo "Uso: ./git-update.sh \"descrizione della modifica\""
    exit 1
fi

rosso()  { printf '\033[31m%s\033[0m\n' "$1"; }
verde()  { printf '\033[32m%s\033[0m\n' "$1"; }
giallo() { printf '\033[33m%s\033[0m\n' "$1"; }

echo "═══════════════════════════════════════════════"
echo "  1/5 — Stato del repository"
echo "═══════════════════════════════════════════════"
git status --short
echo ""

# --- 2. Pattern evidentemente pericolosi, anche se non ancora "staged" ---
# Controllo di primo livello, indipendente da .gitignore: se uno di questi
# nomi comparisse fra i file nuovi/modificati ci si ferma comunque, anche
# se qualcuno ha tolto la riga corrispondente dal .gitignore per errore.
echo "═══════════════════════════════════════════════"
echo "  2/5 — Controllo file sensibili"
echo "═══════════════════════════════════════════════"

PATTERN_PERICOLOSI='(^|/)\.env($|\.)|\.pem$|\.key$|id_rsa|id_ed25519|\.sqlite3?$|\.db$|/backup(/|$)|/data/(logs|cache)/|\.log$'

CANDIDATI=$(git status --porcelain | awk '{print $2}')
TROVATI=""
for f in $CANDIDATI; do
    if echo "$f" | grep -qiE "$PATTERN_PERICOLOSI"; then
        TROVATI="$TROVATI$f"$'\n'
    fi
done

if [ -n "$TROVATI" ]; then
    rosso "✗ File che sembrano sensibili fra le modifiche:"
    echo "$TROVATI"
    rosso "Commit interrotto. Se sono davvero da escludere, aggiungili a"
    rosso ".gitignore; se invece devono entrare nel repository, controllali"
    rosso "a mano e rilancia lo script."
    exit 1
fi
verde "✓ Nessun nome di file sospetto"
echo ""

# --- 3. Cosa verra' davvero aggiunto: si aggiunge solo cio' che e' gia' ---
#         tracciato o esplicitamente nuovo, mai una "git add -A" cieca.
echo "═══════════════════════════════════════════════"
echo "  3/5 — File che verranno committati"
echo "═══════════════════════════════════════════════"
git add -A -n   # dry-run: mostra cosa farebbe "git add -A", senza farlo

echo ""
giallo "Controlla l'elenco sopra. Premi Invio per confermare, Ctrl+C per annullare."
read -r _

git add -A

# Ultimo controllo, questa volta sui file davvero in staging: individua
# anche un secret finito per errore in un file che di per se' non ha un
# nome sospetto (es. una chiave incollata dentro un .py).
if command -v gitleaks >/dev/null 2>&1; then
    echo ""
    echo "Secret scanning sui file in staging…"
    if ! gitleaks protect --staged --redact -v; then
        rosso "✗ gitleaks ha trovato qualcosa che sembra un segreto."
        rosso "Commit interrotto. Vedi l'output sopra (segreti mascherati)."
        git reset >/dev/null
        exit 1
    fi
    verde "✓ Nessun segreto rilevato"
else
    giallo "⚠ gitleaks non installato: salto il secret scanning approfondito."
    giallo "  Installazione: vedi https://github.com/gitleaks/gitleaks"
fi
echo ""

# --- 4. Test essenziali ---
echo "═══════════════════════════════════════════════"
echo "  4/5 — Test"
echo "═══════════════════════════════════════════════"
if [ -x venv/bin/python ]; then
    if ! venv/bin/python -m pytest tests -q; then
        rosso "✗ Test falliti. Commit interrotto."
        git reset >/dev/null
        exit 1
    fi
    verde "✓ Test passati"
else
    giallo "⚠ venv non trovato: salto i test. Eseguili a mano prima di fidarti del push."
fi
echo ""

# --- 5. Commit e push ---
echo "═══════════════════════════════════════════════"
echo "  5/5 — Commit e push"
echo "═══════════════════════════════════════════════"
git commit -m "$MSG"
verde "✓ Commit creato: $(git log -1 --oneline)"

if git remote get-url origin >/dev/null 2>&1; then
    git push origin HEAD
    verde "✓ Push completato"
else
    giallo "⚠ Nessun remote 'origin' configurato: commit locale soltanto."
fi
