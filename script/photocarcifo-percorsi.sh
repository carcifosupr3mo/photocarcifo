#!/usr/bin/env bash
# Genera l'elenco completo dei percorsi con spiegazione e comando.
APP=/opt/photocarcifo
OUT="$APP/docs/PERCORSI.txt"
mkdir -p "$APP/docs"

v(){ printf '%s\n   COS%s\n   LEGATO A   %s\n   COMANDO    %s\n\n' \
     "$1" "'È      $2" "$3" "$4"; }
sez(){ printf '\n══════════════════════════════════════════════════════════════\n  %s\n══════════════════════════════════════════════════════════════\n\n' "$1"; }

{
cat << 'TESTA'
╔══════════════════════════════════════════════════════════════╗
║   PHOTOCARCIFO — DOVE SI TROVA OGNI COSA                     ║
╚══════════════════════════════════════════════════════════════╝

Come orientarsi, in breve:

  cambio l'ASPETTO di qualcosa      →  static/css/style.css
  cambio COSA SUCCEDE cliccando     →  un file in static/js/
  cambio IL TESTO di una pagina     →  un file in templates/
  cambio QUALI DATI arrivano        →  un file in routers/

Comandi utili sempre:
  mappa                      elenco rapido a schermo
  mappa cerca PAROLA         trova in quale file sta una cosa
  photocarcifo-diagnosi.sh   verifica che tutto funzioni
  photocarcifo-salva.sh      copia di sicurezza prima di modificare

DOPO OGNI MODIFICA AL CODICE:
  cd /opt/photocarcifo
  find app -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null
  systemctl restart photocarcifo
TESTA

sez "CERVELLO — la logica del sito"

v "/opt/photocarcifo/app/main.py" \
  "Avvio del sito, intestazioni di sicurezza, pagine di errore." \
  "Dichiara tutte le rotte di routers/. Aggiungendone una, va scritta qui." \
  "nano /opt/photocarcifo/app/main.py"

v "/opt/photocarcifo/app/config.py" \
  "Legge le impostazioni dal file .env (indirizzo del sito, percorsi, chiavi)." \
  "Rifiuta variabili non dichiarate: aggiungerne una a .env senza dichiararla qui blocca il sito." \
  "nano /opt/photocarcifo/app/config.py"

v "/opt/photocarcifo/app/database.py" \
  "Accesso al database, registro eventi, statistiche di visita." \
  "Usato da tutte le rotte. Contiene anche l'accumulo delle visite." \
  "nano /opt/photocarcifo/app/database.py"

v "/opt/photocarcifo/app/security.py" \
  "Cifratura password, protezione dei moduli, limite tentativi di accesso." \
  "Usato da auth.py, twofa.py, upload.py, trash.py, preferiti.py." \
  "nano /opt/photocarcifo/app/security.py"

v "/opt/photocarcifo/app/deps.py" \
  "Stabilisce chi è collegato e cosa può fare." \
  "Ogni pagina del pannello passa da qui per verificare i permessi." \
  "nano /opt/photocarcifo/app/deps.py"

v "/opt/photocarcifo/app/templating.py" \
  "Prepara le pagine HTML e numera CSS e JS per aggiornare la cache." \
  "La funzione asset() fa arrivare subito le modifiche grafiche ai browser." \
  "nano /opt/photocarcifo/app/templating.py"

v "/opt/photocarcifo/app/scanner.py" \
  "Legge il NAS e costruisce l'albero degli album." \
  "Contiene IGNORE_DIRS: le cartelle da saltare (_cestino, _backup_sito...)." \
  "nano /opt/photocarcifo/app/scanner.py"

v "/opt/photocarcifo/app/thumbnails.py" \
  "Crea le miniature nelle tre misure (640, 1280, 1800 pixel)." \
  "Usato da media.py e dalla preparazione notturna. Cambiando qui, le vecchie miniature restano finché non cambia la versione della chiave." \
  "nano /opt/photocarcifo/app/thumbnails.py"

sez "ROTTE — cosa risponde a ogni indirizzo"

v "/opt/photocarcifo/app/routers/tree.py" \
  "Home, album, ricerca, link privati, scadenze, pagina condizioni." \
  "IL PIÙ IMPORTANTE. Decide chi vede cosa. Legato a node.html, home.html, media.py." \
  "nano /opt/photocarcifo/app/routers/tree.py"

v "/opt/photocarcifo/app/routers/media.py" \
  "Serve miniature, anteprime, download singoli, filmati e archivi ZIP." \
  "La funzione _can_access() protegge tutto: ogni nuova rotta che serve file deve chiamarla." \
  "nano /opt/photocarcifo/app/routers/media.py"

v "/opt/photocarcifo/app/routers/auth.py" \
  "Accesso e uscita dal pannello." \
  "Legato a security.py, deps.py, login.html." \
  "nano /opt/photocarcifo/app/routers/auth.py"

v "/opt/photocarcifo/app/routers/twofa.py" \
  "Verifica in due passaggi con applicazione sul telefono." \
  "Se resti chiuso fuori: sqlite3 .../photocarcifo.db \"UPDATE users SET totp_enabled=0, totp_secret=NULL;\"" \
  "nano /opt/photocarcifo/app/routers/twofa.py"

v "/opt/photocarcifo/app/routers/admin.py" \
  "Pannello di controllo e statistiche." \
  "Legato a dashboard.html." \
  "nano /opt/photocarcifo/app/routers/admin.py"

v "/opt/photocarcifo/app/routers/admin_nodes.py" \
  "Dati per la gestione album: rinomina, privacy, scadenze, condivisione." \
  "Legato a admin-tree.js e tree.html. Non tocca mai i file sul NAS." \
  "nano /opt/photocarcifo/app/routers/admin_nodes.py"

v "/opt/photocarcifo/app/routers/upload.py" \
  "Caricamento fotografie dal pannello." \
  "Scrive su /mnt/magazzino-rw. Può solo creare, mai cancellare." \
  "nano /opt/photocarcifo/app/routers/upload.py"

v "/opt/photocarcifo/app/routers/trash.py" \
  "Cestino: sposta in _CESTINO sul NAS, con ripristino." \
  "Non cancella nulla davvero: lo svuotamento si fa da File Station." \
  "nano /opt/photocarcifo/app/routers/trash.py"

v "/opt/photocarcifo/app/routers/preferiti.py" \
  "Cuori dei clienti, richiesta del nome, pagina delle proprie scelte." \
  "Legato a preferiti.js, preferiti-nome.js, mie_preferite.html." \
  "nano /opt/photocarcifo/app/routers/preferiti.py"

v "/opt/photocarcifo/app/routers/pref_admin.py" \
  "Pagina del pannello con tutte le scelte dei clienti." \
  "Legato a preferite.html e admin-preferite.js." \
  "nano /opt/photocarcifo/app/routers/pref_admin.py"

v "/opt/photocarcifo/app/routers/seo.py" \
  "robots.txt, sitemap.xml e sitemap delle immagini." \
  "Usa SITE_URL da .env. Esclude album privati e nascosti." \
  "nano /opt/photocarcifo/app/routers/seo.py"

sez "PAGINE PUBBLICHE — quello che vedono i visitatori"

v "/opt/photocarcifo/app/templates/base.html" \
  "Struttura comune: intestazione, piè di pagina, richiamo di CSS e JS." \
  "Modificando qui cambiano TUTTE le pagine. Contiene il pulsante Accedi." \
  "nano /opt/photocarcifo/app/templates/base.html"

v "/opt/photocarcifo/app/templates/public/home.html" \
  "Prima pagina con presentazione e categorie." \
  "Riceve i dati da tree.py, funzione home()." \
  "nano /opt/photocarcifo/app/templates/public/home.html"

v "/opt/photocarcifo/app/templates/public/node.html" \
  "Album: griglia fotografie, ordinamento, scelta della vista, selezione." \
  "LA PIÙ COMPLESSA. Riceve i dati da _render_node() in tree.py." \
  "nano /opt/photocarcifo/app/templates/public/node.html"

v "/opt/photocarcifo/app/templates/public/node_password.html" \
  "Richiesta della password per un album riservato." \
  "Mostrata da private_node() in tree.py." \
  "nano /opt/photocarcifo/app/templates/public/node_password.html"

v "/opt/photocarcifo/app/templates/public/node_scaduto.html" \
  "Avviso di link non più valido." \
  "Mostrata quando expires_at è passato." \
  "nano /opt/photocarcifo/app/templates/public/node_scaduto.html"

v "/opt/photocarcifo/app/templates/public/search.html" \
  "Risultati della ricerca." \
  "Riceve i dati da search() in tree.py." \
  "nano /opt/photocarcifo/app/templates/public/search.html"

v "/opt/photocarcifo/app/templates/public/mie_preferite.html" \
  "Le fotografie che il cliente ha segnato col cuore." \
  "Riceve i dati da mie_preferite() in preferiti.py." \
  "nano /opt/photocarcifo/app/templates/public/mie_preferite.html"

v "/opt/photocarcifo/app/templates/public/privacy.html" \
  "Condizioni d'uso, copyright, cookie e privacy." \
  "Richiamata dall'avviso iniziale e dal piè di pagina." \
  "nano /opt/photocarcifo/app/templates/public/privacy.html"

sez "PAGINE DEL PANNELLO — solo per te"

v "/opt/photocarcifo/app/templates/admin/base.html" \
  "Struttura e menu del pannello." \
  "Qui si aggiungono le voci di menu." \
  "nano /opt/photocarcifo/app/templates/admin/base.html"

v "/opt/photocarcifo/app/templates/admin/dashboard.html" \
  "Panoramica con numeri e album più visti." \
  "Riceve i dati da admin.py." \
  "nano /opt/photocarcifo/app/templates/admin/dashboard.html"

v "/opt/photocarcifo/app/templates/admin/tree.html" \
  "Gestione album con schede e menu a tre puntini." \
  "Il comportamento sta in admin-tree.js." \
  "nano /opt/photocarcifo/app/templates/admin/tree.html"

v "/opt/photocarcifo/app/templates/admin/upload.html" \
  "Pagina di caricamento fotografie." \
  "Il comportamento sta in admin-upload.js." \
  "nano /opt/photocarcifo/app/templates/admin/upload.html"

v "/opt/photocarcifo/app/templates/admin/trash.html" \
  "Cestino con i gruppi da ripristinare." \
  "Legata a trash.py." \
  "nano /opt/photocarcifo/app/templates/admin/trash.html"

v "/opt/photocarcifo/app/templates/admin/preferite.html" \
  "Scelte dei clienti, divise per album." \
  "Il comportamento sta in admin-preferite.js." \
  "nano /opt/photocarcifo/app/templates/admin/preferite.html"

sez "ASPETTO E COMPORTAMENTO"

v "/opt/photocarcifo/app/static/css/style.css" \
  "TUTTO l'aspetto del sito: colori, spaziature, griglie, telefono." \
  "File unico e molto lungo. Le aggiunte recenti stanno in fondo." \
  "nano /opt/photocarcifo/app/static/css/style.css"

v "/opt/photocarcifo/app/static/js/app.js" \
  "Caricamento progressivo, visualizzatore, selezione multipla, rimozione." \
  "Legato a node.html. La selezione sopravvive al cambio pagina." \
  "nano /opt/photocarcifo/app/static/js/app.js"

v "/opt/photocarcifo/app/static/js/vista.js" \
  "Scelta fra griglia e vista grande, ricordata dal browser." \
  "Legato ai pulsanti in node.html." \
  "nano /opt/photocarcifo/app/static/js/vista.js"

v "/opt/photocarcifo/app/static/js/preferiti.js" \
  "Cuore su ogni fotografia e pulsante di scaricamento delle preferite." \
  "Chiama le rotte di preferiti.py." \
  "nano /opt/photocarcifo/app/static/js/preferiti.js"

v "/opt/photocarcifo/app/static/js/preferiti-nome.js" \
  "Richiesta del profilo Instagram o del nome prima di scegliere." \
  "Compare una volta per sessione." \
  "nano /opt/photocarcifo/app/static/js/preferiti-nome.js"

v "/opt/photocarcifo/app/static/js/ospite-nav.js" \
  "Sostituisce Accedi con il nome del cliente." \
  "Legge il cookie pc_nome. Legato a base.html." \
  "nano /opt/photocarcifo/app/static/js/ospite-nav.js"

v "/opt/photocarcifo/app/static/js/cookie-avviso.js" \
  "Avviso iniziale su copyright e cookie." \
  "Richiama la pagina privacy. Ricordato per un anno." \
  "nano /opt/photocarcifo/app/static/js/cookie-avviso.js"

v "/opt/photocarcifo/app/static/js/admin-tree.js" \
  "Gestione album: menu, condivisione, scadenze, preferite." \
  "Il più complesso del pannello. Legato a tree.html e admin_nodes.py." \
  "nano /opt/photocarcifo/app/static/js/admin-tree.js"

v "/opt/photocarcifo/app/static/js/admin-upload.js" \
  "Caricamento con tre file per volta e avanzamento." \
  "Legato a upload.html e upload.py." \
  "nano /opt/photocarcifo/app/static/js/admin-upload.js"

v "/opt/photocarcifo/app/static/js/admin-preferite.js" \
  "Elenco delle scelte dei clienti, con rimozione." \
  "Legato a preferite.html e pref_admin.py." \
  "nano /opt/photocarcifo/app/static/js/admin-preferite.js"

sez "DATI, CARTELLE E COPIE"

v "/opt/photocarcifo/data/photocarcifo.db" \
  "Indice di tutte le fotografie, album, utenti, preferiti, statistiche." \
  "IL FILE PIÙ IMPORTANTE dopo le fotografie. Salvato ogni notte." \
  "sqlite3 /opt/photocarcifo/data/photocarcifo.db"

v "/opt/photocarcifo/data/cache/thumbnails/" \
  "Miniature già pronte (circa 17 GB). Si rigenerano da sole." \
  "Cancellabili senza perdere nulla, ma il sito diventa lento finché non si ricreano." \
  "du -sh /opt/photocarcifo/data/cache/thumbnails"

v "/opt/photocarcifo/backup/aggiornamenti/" \
  "Copie automatiche create ogni notte prima degli aggiornamenti. Restano le 3 più recenti." \
  "Create da photocarcifo-notte.sh." \
  "ls -lh /opt/photocarcifo/backup/aggiornamenti/"

v "/opt/photocarcifo/backup/personali/" \
  "Copie create da te. Non vengono MAI cancellate automaticamente." \
  "Create con photocarcifo-salva.sh." \
  "ls -lh /opt/photocarcifo/backup/personali/"

v "/opt/photocarcifo/.env" \
  "Configurazione riservata: chiavi, indirizzo del sito, percorsi." \
  "ATTENZIONE: una variabile non prevista da config.py blocca il sito." \
  "nano /opt/photocarcifo/.env"

v "/opt/photocarcifo/docs/" \
  "Documentazione: architettura, mappa file, questo elenco." \
  "Rigenerabile con photocarcifo-mappa-file.sh." \
  "ls -lh /opt/photocarcifo/docs/"

v "/mnt/magazzino/" \
  "Le fotografie sul NAS, in SOLA LETTURA. Fonte ufficiale delle immagini." \
  "Il sito legge da qui e non può modificarle." \
  "ls /mnt/magazzino/"

v "/mnt/magazzino-rw/" \
  "Stesso archivio, in scrittura. Usato solo da caricamento e cestino." \
  "Contiene _CESTINO e _backup_sito, esclusi dalla scansione." \
  "ls /mnt/magazzino-rw/"

sez "CONFIGURAZIONI DI SISTEMA"

v "/etc/nginx/sites-available/photocarcifo" \
  "Sito principale: HTTPS, cache miniature, limiti, sicurezza." \
  "Dopo ogni modifica: nginx -t && systemctl reload nginx" \
  "nano /etc/nginx/sites-available/photocarcifo"

v "/etc/nginx/sites-available/meteo" \
  "Inoltra meteo.photocarcifo.ch al contenitore 204, porta 8000." \
  "Indipendente dal sito fotografico." \
  "nano /etc/nginx/sites-available/meteo"

v "/etc/nginx/sites-available/000-default-catchall" \
  "Risponde 410 ai domini non tuoi (per esempio kappakappa.ch)." \
  "Serve a farli sparire dai motori di ricerca." \
  "nano /etc/nginx/sites-available/000-default-catchall"

v "/etc/systemd/system/photocarcifo.service" \
  "Il servizio che tiene acceso il sito." \
  "Dopo ogni modifica: systemctl daemon-reload && systemctl restart photocarcifo" \
  "nano /etc/systemd/system/photocarcifo.service"

sez "COMANDI"

v "/usr/local/bin/mappa" \
  "Elenco rapido a schermo. Anche: mappa cerca PAROLA" \
  "Non modifica nulla." \
  "mappa"

v "/usr/local/bin/photocarcifo-diagnosi.sh" \
  "Verifica che ogni contenuto sia visibile a chi ha diritto e bloccato agli altri." \
  "DA USARE DOPO OGNI MODIFICA." \
  "photocarcifo-diagnosi.sh"

v "/usr/local/bin/photocarcifo-salva.sh" \
  "Copia di sicurezza manuale in backup/personali." \
  "Da fare PRIMA di modifiche importanti." \
  "photocarcifo-salva.sh prima-di-modifiche"

v "/usr/local/bin/photocarcifo-notte.sh" \
  "Manutenzione notturna alle 04:30: copia, aggiorna, verifica, ripristina se serve." \
  "Registro: tail -40 /var/log/photocarcifo-notte.log" \
  "nano /usr/local/bin/photocarcifo-notte.sh"

v "/usr/local/bin/photocarcifo-pregen.py" \
  "Prepara le miniature durante la notte (01:00–04:15)." \
  "Si ferma sotto i 6 GB liberi." \
  "nano /usr/local/bin/photocarcifo-pregen.py"

v "/usr/local/bin/photocarcifo-percorsi.sh" \
  "Rigenera questo elenco." \
  "Da lanciare dopo aver aggiunto file nuovi." \
  "photocarcifo-percorsi.sh"

sez "SE QUALCOSA VA STORTO"

cat << 'FONDO'
IL SITO NON RISPONDE
   journalctl -u photocarcifo -n 30 --no-pager
   systemctl restart photocarcifo

ERRORE 500 SU UNA PAGINA
   journalctl -u photocarcifo -n 20 --no-pager | tail -12

CHIUSO FUORI DAL PANNELLO
   sqlite3 /opt/photocarcifo/data/photocarcifo.db \
     "UPDATE users SET totp_enabled=0, totp_secret=NULL;"

MODIFICA SBAGLIATA, VOGLIO TORNARE INDIETRO
   ls -lt /opt/photocarcifo/backup/aggiornamenti/
   systemctl stop photocarcifo
   tar -xzf /opt/photocarcifo/backup/aggiornamenti/NOMEFILE.tar.gz -C /opt
   chown -R photocarcifo:photocarcifo /opt/photocarcifo/app
   systemctl start photocarcifo

SPAZIO ESAURITO
   df -h /
   du -sh --exclude=/mnt /opt /var 2>/dev/null | sort -rh
   apt-get clean && journalctl --vacuum-size=100M

VERIFICA GENERALE
   photocarcifo-diagnosi.sh
FONDO

printf '\n\nGenerato il %s\n' "$(date '+%d/%m/%Y alle %H:%M')"
} > "$OUT"

echo "Creato: $OUT"
wc -l "$OUT"
du -h "$OUT" | cut -f1 | xargs echo "Dimensione:"
