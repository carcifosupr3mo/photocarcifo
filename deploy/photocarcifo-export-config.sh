#!/usr/bin/env bash
# Copia sul NAS tutto cio' che serve a ricostruire il servizio e che NON
# vive nel repository git.
#
# Il perche': se il container Proxmox viene perso, il repository e il NAS
# sopravvivono, ma 22 unit systemd su 27, la configurazione nginx in uso
# (perfezionata a mano rispetto al modello in deploy/nginx.conf) e lo
# script di backup del database esistono solo dentro il container. Senza
# questa copia, ricostruire il sito vorrebbe dire riscriverli a memoria.
#
# Il backup del database gia' esiste (photocarcifo-db-backup.sh) ma scrive
# in /opt/photocarcifo-db-backup, cioe' sullo stesso container: nello
# scenario "container distrutto" sparirebbe insieme a tutto il resto. Qui
# se ne porta una copia anche sul NAS.
#
# Destinazione: _backup_sito sul NAS. E' gia' nella lista IGNORE_DIRS
# dello scanner (app/scanner.py), quindi non diventa una categoria del
# sito, ed e' gia' la cartella dove finivano i backup del database fino ad
# agosto 2026.
#
# I segreti NON vengono copiati in chiaro: di .env e del file Telegram si
# salva solo l'elenco delle chiavi, senza i valori. I valori veri vanno
# tenuti dove gia' stanno (password manager); il database, che contiene
# l'hash della password admin e il segreto 2FA, e' gia' protetto dai
# permessi della sua cartella.
set -uo pipefail

APP=/opt/photocarcifo
DEST=/mnt/magazzino-rw/_backup_sito/configurazione
DB_BACKUP_DIR=/opt/photocarcifo-db-backup
LOG=/var/log/photocarcifo-export-config.log
LOCK=/var/lock/photocarcifo-export-config.lock

# Un'esecuzione manuale mentre gira quella notturna del timer non deve
# sovrapporsi: la rotazione sotto cancella file in base a un elenco letto
# a inizio ciclo, due istanze insieme potrebbero cancellarsi a vicenda il
# backup appena scritto dall'altra.
exec 9>"$LOCK"
flock -n 9 || { echo "Un'altra esecuzione e' gia' in corso, esco."; exit 0; }

exec >>"$LOG" 2>&1
echo ""
echo "═══════════ $(date '+%H:%M') — inizio export configurazione ═══════════"

errori=0
fallito() {
    echo "  ERRORE: $1"
    errori=$((errori + 1))
}

# Il NAS deve essere davvero montato, non solo esistere come cartella:
# stessa distinzione di app/scanner.py (_nas_disponibile), altrimenti si
# scriverebbe nella cartella locale vuota rimasta al posto del mount.
if ! mountpoint -q /mnt/magazzino-rw; then
    echo "  NAS non montato (/mnt/magazzino-rw): export annullato"
    echo "═══════════ $(date '+%H:%M') — fine (saltato) ═══════════"
    exit 1
fi

mkdir -p "$DEST"/{systemd,nginx,script,runbook} || {
    echo "  impossibile creare $DEST"
    exit 1
}
# La cartella sul NAS (_backup_sito) e' condivisa con permessi troppo
# larghi (777, verificato: chiunque sulla rete locale con accesso NFS puo'
# scrivervi). Il backup del database che finisce qui dentro porta con se'
# l'hash della password admin e il segreto 2FA (tabella users): la
# cartella dedicata a questo export si restringe subito, stesso principio
# gia' applicato da photocarcifo-db-backup.sh alla sua destinazione sul
# container ("la destinazione non deve essere leggibile da chiunque").
chmod 700 "$DEST" "$(dirname "$DEST")" 2>/dev/null || true

echo "▸ Unit systemd"
copiate=0
for f in /etc/systemd/system/photocarcifo*.service /etc/systemd/system/photocarcifo*.timer; do
    [ -e "$f" ] || continue
    cp "$f" "$DEST/systemd/" || fallito "copia di $f"
    copiate=$((copiate + 1))
done
echo "  unit copiate: $copiate"

echo "▸ Configurazione nginx"
# La configurazione in uso, non il modello del repository: e' quella che
# ha i certificati, i limiti di richiesta e le regole degli automi.
cp /etc/nginx/sites-available/photocarcifo "$DEST/nginx/" 2>/dev/null \
    || fallito "copia di sites-available/photocarcifo"
if [ -d /etc/nginx/snippets ]; then
    mkdir -p "$DEST/nginx/snippets"
    cp /etc/nginx/snippets/photocarcifo-*.conf "$DEST/nginx/snippets/" 2>/dev/null \
        || echo "  (nessuno snippet photocarcifo-* da copiare)"
fi

echo "▸ Script fuori repository"
# Quasi tutti gli script in /usr/local/bin sono collegamenti al repository
# e quindi gia' versionati: si copiano solo i file veri, che sono gli
# unici a rischio.
copiati=0
for f in /usr/local/bin/photocarcifo-*; do
    [ -f "$f" ] && [ ! -L "$f" ] || continue
    cp "$f" "$DEST/script/" || fallito "copia di $f"
    copiati=$((copiati + 1))
done
echo "  script copiati (non collegamenti): $copiati"

echo "▸ Voci fstab dei mount NAS"
grep -E 'magazzino' /etc/fstab > "$DEST/fstab-magazzino.txt" 2>/dev/null \
    || fallito "estrazione voci fstab"

echo "▸ Elenco chiavi di configurazione (senza valori)"
# Solo i nomi delle chiavi: serve a sapere COSA va riempito al ripristino,
# non a portarsi dietro i segreti.
if [ -f "$APP/.env" ]; then
    sed 's/=.*/=/' "$APP/.env" > "$DEST/env-chiavi.txt" || fallito "sanitizzazione .env"
    chmod 644 "$DEST/env-chiavi.txt" 2>/dev/null
fi
if [ -f /etc/photocarcifo-telegram.conf ]; then
    sed 's/=.*/=/' /etc/photocarcifo-telegram.conf > "$DEST/telegram-chiavi.txt" \
        || fallito "sanitizzazione telegram.conf"
fi

echo "▸ Runbook di ripristino"
if [ -f "$APP/docs/DISASTER_RECOVERY.md" ]; then
    cp "$APP/docs/DISASTER_RECOVERY.md" "$DEST/runbook/" || fallito "copia runbook"
fi

echo "▸ Copia del backup database piu' recente"
# Il backup giornaliero vive sul container: qui se ne porta l'ultima copia
# anche sul NAS, che e' l'unica cosa che sopravvive se il container muore.
ultimo=$(ls -1t "$DB_BACKUP_DIR"/photocarcifo-*.sqlite 2>/dev/null | head -1)
if [ -n "$ultimo" ]; then
    nome=$(basename "$ultimo")
    if cp "$ultimo" "$DEST/../$nome.tmp" && mv "$DEST/../$nome.tmp" "$DEST/../$nome"; then
        echo "  copiato: $nome"
    else
        fallito "copia del backup database"
        rm -f "$DEST/../$nome.tmp"
    fi
    # Tiene 7 giorni di database sul NAS: le copie complete stanno gia'
    # sul container (14 giorni), qui basta la finestra piu' recente. Il
    # nome "photocarcifo-AAAA-MM-GG.sqlite" e' lo stesso prodotto da
    # photocarcifo-db-backup.sh: la rotazione tocca solo file con questo
    # nome esatto, non un file diverso lasciato da qualcun altro nella
    # stessa cartella condivisa.
    # Letta in una variabile invece che in pipe diretta al while: in bash
    # l'ultimo anello di una pipeline gira in una subshell, e un errore
    # contato li' dentro (fallito, che incrementa $errori) andrebbe perso
    # appena la subshell finisce.
    vecchi=$(ls -1t "$DEST"/../photocarcifo-*.sqlite 2>/dev/null \
        | grep -E '/photocarcifo-[0-9]{4}-[0-9]{2}-[0-9]{2}\.sqlite$' \
        | tail -n +8)
    while read -r vecchio; do
        [ -n "$vecchio" ] || continue
        if rm -f "$vecchio"; then
            echo "  rimosso vecchio: $(basename "$vecchio")"
        else
            fallito "rimozione vecchio $vecchio"
        fi
    done <<< "$vecchi"
else
    fallito "nessun backup database trovato in $DB_BACKUP_DIR"
fi

echo "▸ Riepilogo"
echo "  destinazione: $DEST"
du -sh "$DEST" 2>/dev/null | cut -f1 | xargs echo "  spazio usato:"

if [ "$errori" -gt 0 ]; then
    echo "═══════════ $(date '+%H:%M') — fine ($errori errori) ═══════════"
    exit 1
fi
echo "═══════════ $(date '+%H:%M') — fine (ok) ═══════════"
