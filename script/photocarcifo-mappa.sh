#!/usr/bin/env bash
# Genera l'unica mappa del sito, sempre aggiornata.
APP=/opt/photocarcifo
DIR="$APP/MAPPA"
OUT="$DIR/MAPPA.txt"
mkdir -p "$DIR"

v(){ printf '%s\n   COSA FA    %s\n' "$1" "$2"
     [ -n "$3" ] && printf '   LEGATO A   %s\n' "$3"
     [ -n "$4" ] && printf '   COMANDO    %s\n' "$4"
     printf '\n'; }
sez(){ printf '\n──────────────────────────────────────────────────────────────\n  %s\n──────────────────────────────────────────────────────────────\n\n' "$1"; }

{
printf '╔══════════════════════════════════════════════════════════════╗\n'
printf '║   PHOTOCARCIFO — MAPPA DEL SITO                              ║\n'
printf '╚══════════════════════════════════════════════════════════════╝\n\n'
printf 'Aggiornata il %s\n' "$(date '+%d/%m/%Y alle %H:%M')"
printf 'Rigenerala con:  photocarcifo-mappa.sh\n\n'

printf 'COME ORIENTARSI\n'
printf '   aspetto, colori              →  static/css/style.css\n'
printf '   cosa succede cliccando       →  static/js/\n'
printf '   testo di una pagina          →  templates/\n'
printf '   quali dati arrivano          →  routers/\n\n'
printf 'DOPO OGNI MODIFICA AL CODICE\n'
printf '   cd /opt/photocarcifo\n'
printf "   find app -name '__pycache__' -type d -exec rm -rf {} +\n"
printf '   systemctl restart photocarcifo\n\n'
printf 'COMANDI\n'
printf '   mappa                      elenco rapido a schermo\n'
printf '   mappa cerca PAROLA         trova in quale file sta una cosa\n'
printf '   photocarcifo-diagnosi.sh   verifica che tutto funzioni\n'
printf '   photocarcifo-salva.sh X    copia di sicurezza\n'

sez "STATO ATTUALE"
printf '   fotografie          %s\n' "$(sqlite3 "$APP/data/photocarcifo.db" 'SELECT COUNT(*) FROM media;' 2>/dev/null)"
printf '   album               %s\n' "$(sqlite3 "$APP/data/photocarcifo.db" 'SELECT COUNT(*) FROM nodes;' 2>/dev/null)"
printf '   di cui riservati    %s\n' "$(sqlite3 "$APP/data/photocarcifo.db" 'SELECT COUNT(*) FROM nodes WHERE is_private=1;' 2>/dev/null)"
printf '   miniature pronte    %s\n' "$(find "$APP/data/cache/thumbnails" -name '*.jpg' 2>/dev/null | wc -l)"
printf '   preferiti clienti   %s\n' "$(sqlite3 "$APP/data/photocarcifo.db" 'SELECT COUNT(*) FROM preferiti;' 2>/dev/null)"
printf '   spazio libero       %s\n' "$(df -h / | awk 'NR==2{print $4}')"
printf '   sito                %s\n' "$(systemctl is-active photocarcifo)"

sez "IMPIANTO"
printf '   contenitore         192.168.1.206\n'
printf '   archivio foto       NAS 192.168.1.11 (/mnt/magazzino, sola lettura)\n'
printf '   archivio scrivibile /mnt/magazzino-rw (caricamento e cestino)\n'
printf '   meteo               192.168.1.204 porta 8000\n'
printf '   domini              photocarcifo.ch, www, gallery, meteo\n'

sez "CERVELLO — la logica"
v "app/main.py" "Avvio, sicurezza, pagine di errore." \
  "Dichiara tutte le rotte: aggiungendone una va scritta qui." \
  "nano $APP/app/main.py"
v "app/config.py" "Impostazioni lette dal file .env." \
  "Rifiuta variabili non previste: una in piu' in .env blocca il sito." \
  "nano $APP/app/config.py"
v "app/database.py" "Accesso ai dati, registro, statistiche." "" "nano $APP/app/database.py"
v "app/security.py" "Password, protezione moduli, limite tentativi." "" "nano $APP/app/security.py"
v "app/deps.py" "Stabilisce chi e' collegato e cosa puo' fare." "" "nano $APP/app/deps.py"
v "app/templating.py" "Prepara le pagine, numera CSS e JS." \
  "asset() fa arrivare subito le modifiche grafiche." "nano $APP/app/templating.py"
v "app/scanner.py" "Legge il NAS e costruisce l'albero." \
  "IGNORE_DIRS: cartelle da saltare (_cestino, _backup_sito)." "nano $APP/app/scanner.py"
v "app/thumbnails.py" "Miniature a 640, 1280 e 1800 pixel." "" "nano $APP/app/thumbnails.py"

sez "ROTTE — cosa risponde a ogni indirizzo"
v "app/routers/tree.py" "Home, album, ricerca, link privati, scadenze." \
  "IL PIU' IMPORTANTE: decide chi vede cosa." "nano $APP/app/routers/tree.py"
v "app/routers/media.py" "Miniature, anteprime, download, ZIP." \
  "_can_access() protegge tutto: ogni rotta che serve file deve chiamarla." \
  "nano $APP/app/routers/media.py"
v "app/routers/auth.py" "Accesso e uscita." "" "nano $APP/app/routers/auth.py"
v "app/routers/twofa.py" "Verifica in due passaggi." "" "nano $APP/app/routers/twofa.py"
v "app/routers/admin.py" "Pannello e statistiche." "" "nano $APP/app/routers/admin.py"
v "app/routers/admin_nodes.py" "Gestione album: rinomina, privacy, scadenze." \
  "Non tocca mai i file sul NAS." "nano $APP/app/routers/admin_nodes.py"
v "app/routers/upload.py" "Caricamento fotografie." \
  "Puo' solo creare, mai cancellare." "nano $APP/app/routers/upload.py"
v "app/routers/trash.py" "Cestino con ripristino." \
  "Sposta in _CESTINO: non cancella nulla." "nano $APP/app/routers/trash.py"
v "app/routers/preferiti.py" "Cuori dei clienti e richiesta nome." "" "nano $APP/app/routers/preferiti.py"
v "app/routers/pref_admin.py" "Pagina con le scelte dei clienti." "" "nano $APP/app/routers/pref_admin.py"
v "app/routers/seo.py" "robots, sitemap, sitemap immagini." "" "nano $APP/app/routers/seo.py"

sez "PAGINE PUBBLICHE"
v "app/templates/base.html" "Struttura comune di tutte le pagine." \
  "Modificando qui cambia TUTTO il sito." "nano $APP/app/templates/base.html"
v "app/templates/public/home.html" "Prima pagina." "" "nano $APP/app/templates/public/home.html"
v "app/templates/public/node.html" "Album: griglia, ordinamento, vista." \
  "LA PIU' COMPLESSA." "nano $APP/app/templates/public/node.html"
v "app/templates/public/node_password.html" "Richiesta password." "" ""
v "app/templates/public/node_scaduto.html" "Link non piu' valido." "" ""
v "app/templates/public/search.html" "Risultati ricerca." "" ""
v "app/templates/public/mie_preferite.html" "Scelte del cliente." "" ""
v "app/templates/public/privacy.html" "Condizioni, copyright, cookie." "" ""

sez "PAGINE DEL PANNELLO"
v "app/templates/admin/base.html" "Struttura e menu." \
  "Qui si aggiungono le voci di menu." "nano $APP/app/templates/admin/base.html"
v "app/templates/admin/dashboard.html" "Panoramica." "" ""
v "app/templates/admin/tree.html" "Gestione album." "Comportamento in admin-tree.js." ""
v "app/templates/admin/upload.html" "Caricamento." "" ""
v "app/templates/admin/trash.html" "Cestino." "" ""
v "app/templates/admin/preferite.html" "Scelte dei clienti." "" ""

sez "ASPETTO E COMPORTAMENTO"
v "app/static/css/style.css" "TUTTO l'aspetto del sito." \
  "File unico: le aggiunte recenti stanno in fondo." "nano $APP/app/static/css/style.css"
v "app/static/js/app.js" "Visualizzatore, selezione, rimozione." "" "nano $APP/app/static/js/app.js"
v "app/static/js/vista.js" "Griglia o vista grande." "" ""
v "app/static/js/preferiti.js" "Cuore sulle fotografie." "" ""
v "app/static/js/preferiti-nome.js" "Richiesta del nome." "" ""
v "app/static/js/ospite-nav.js" "Nome del cliente al posto di Accedi." "" ""
v "app/static/js/cookie-avviso.js" "Avviso iniziale." "" ""
v "app/static/js/admin-tree.js" "Gestione album." "Il piu' complesso del pannello." ""
v "app/static/js/admin-upload.js" "Caricamento." "" ""
v "app/static/js/admin-preferite.js" "Scelte dei clienti." "" ""

sez "DATI E COPIE"
v "data/photocarcifo.db" "Indice di foto, album, utenti, preferiti." \
  "IL FILE PIU' IMPORTANTE dopo le fotografie." "sqlite3 $APP/data/photocarcifo.db"
v "data/cache/thumbnails/" "Miniature pronte. Si rigenerano da sole." "" \
  "du -sh $APP/data/cache/thumbnails"
v "backup/aggiornamenti/" "Copie notturne: restano le 3 piu' recenti." "" \
  "ls -lh '$APP/backup/aggiornamenti/'"
v "backup/personali/" "Copie fatte da te: mai cancellate." "" \
  "ls -lh '$APP/backup/personali/'"
v ".env" "Configurazione riservata." \
  "Una variabile non prevista blocca il sito." "nano $APP/.env"

sez "CONFIGURAZIONI DI SISTEMA"
v "/etc/nginx/sites-available/photocarcifo" "Sito, HTTPS, cache, sicurezza." \
  "Dopo le modifiche: nginx -t && systemctl reload nginx" \
  "nano /etc/nginx/sites-available/photocarcifo"
v "/etc/nginx/sites-available/meteo" "Meteo verso il 204." "" ""
v "/etc/nginx/sites-available/000-default-catchall" "Domini non tuoi: 410." "" ""
v "/etc/systemd/system/photocarcifo.service" "Servizio del sito." \
  "Dopo le modifiche: systemctl daemon-reload" ""

sez "AUTOMATISMI NOTTURNI"
systemctl list-timers 'photocarcifo*' --no-pager 2>/dev/null | \
  awk 'NR>1 && /photocarcifo/ {printf "   %-28s %s %s %s\n", $NF, $1, $2, $3}' | head -6
printf '\n   01:00–04:15  prepara le miniature\n'
printf '   04:30        copia, aggiorna, verifica, ripristina se serve\n'
printf '   05:00        cambia le copertine\n'

sez "FILE MODIFICATI NEGLI ULTIMI 7 GIORNI"
find "$APP/app" -type f -mtime -7 -not -path '*__pycache__*' 2>/dev/null | \
  sed "s|$APP/|   |" | sort

sez "SE QUALCOSA VA STORTO"
cat << 'FONDO'
   IL SITO NON RISPONDE
      journalctl -u photocarcifo -n 30 --no-pager
      systemctl restart photocarcifo

   ERRORE 500
      journalctl -u photocarcifo -n 20 --no-pager | tail -12

   CHIUSO FUORI DAL PANNELLO
      sqlite3 /opt/photocarcifo/data/photocarcifo.db \
        "UPDATE users SET totp_enabled=0, totp_secret=NULL;"

   TORNARE INDIETRO
      ls -lt /opt/photocarcifo/backup/aggiornamenti/
      systemctl stop photocarcifo
      tar -xzf .../NOMEFILE.tar.gz -C /opt
      chown -R photocarcifo:photocarcifo /opt/photocarcifo/app
      systemctl start photocarcifo

   SPAZIO ESAURITO
      df -h /
      apt-get clean && journalctl --vacuum-size=100M

   FOTO PRIVATE CHE NON CARICANO
      Il cookie pc_unlock deve arrivare aprendo il link.
      Verifica con: photocarcifo-diagnosi.sh
FONDO
} > "$OUT"

echo "Aggiornata: $OUT"
wc -l "$OUT" | awk '{print $1 " righe"}'
