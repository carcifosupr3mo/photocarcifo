# PHOTOCARCIFO - README

> Creato: 16/09/2026

> Autore: Nathan Pollini

> Progetto: PHOTOCARCIFO

> GitHub: https://github.com/carcifosupr3mo/photocarcifo

Portfolio fotografico self-hosted per fotografia sportiva (motorsport, BMX, ciclismo, atletica). Serve le fotografie direttamente da un NAS tramite un'applicazione Python, senza copiarle mai altrove.

## Caratteristiche

- **Galleria pubblica ad albero**: categorie → album → sotto-album → foto/video, organizzata per disciplina sportiva.
- **Album privati**: link con token dedicato, password opzionale e scadenza — pensati per consegnare gli scatti di uno shooting a un singolo cliente.
- **Ricerca per numero di gara**: trova tutte le foto in cui compare un pettorale, con lettura automatica dei numeri via OCR (RapidOCR) più correzione manuale dal pannello.
- **Download**: singolo file o archivio ZIP per un intero album o una selezione, generato in streaming senza caricare tutto in memoria.
- **Preferiti**: i visitatori possono segnare le foto che preferiscono senza registrarsi.
- **App web installabile (PWA)**: versione ottimizzata per mobile, con notifiche push quando un nuovo album è pronto.
- **Pannello di amministrazione**: gestione album/media/utenti, autenticazione a due fattori (TOTP), condivisione rapida via link.
- **Multilingua**: italiano, inglese, francese, tedesco, spagnolo.
- **Recensioni** pubbliche moderate e **modulo di contatto**.
- **SEO**: sitemap XML/immagini, notifica automatica ai motori di ricerca (IndexNow) quando cambia un contenuto pubblico.
- **Manutenzione automatica**: scansione incrementale del NAS, generazione miniature, backup del database.

## Tecnologie

- **Backend**: Python 3, FastAPI, Uvicorn
- **Database**: SQLite (modalità WAL)
- **Template/Frontend**: Jinja2, HTML/CSS/JavaScript (nessun framework SPA, nessun bundler)
- **PWA**: JavaScript nativo, Service Worker, Web Push (VAPID)
- **Web server**: Nginx (reverse proxy, cache, TLS)
- **Sicurezza**: Argon2 per l'hashing delle password, autenticazione a due fattori (TOTP), fail2ban
- **Automazione**: systemd (servizi e timer per scansione, manutenzione, backup)
- **Immagini**: Pillow, RapidOCR (opzionale, per la lettura dei numeri di gara)

## Struttura del progetto

photocarcifo/

├── app/        # applicazione FastAPI: routing, sicurezza, scansione NAS, miniature, template

├── config/     # configurazione di servizio (es. Nginx)

├── deploy/     # script di installazione, unità systemd, configurazione di deploy

├── docs/       # documentazione tecnica approfondita

├── script/     # script operativi (manutenzione, diagnosi, automazioni)

└── tests/      # suite di test automatici


## Installazione

chmod +x deploy/install.sh
sudo ./deploy/install.sh

Per la configurazione completa, i requisiti di infrastruttura e la procedura di ripristino, vedi la documentazione in `docs/`.

## Testing

pytest tests -q

(Test contro una copia isolata e sanificata del database, mai contro i dati reali.)

## Sicurezza

- Autorizzazione centralizzata su ogni contenuto.
- Password con hashing Argon2id, 2FA opzionale.
- CSRF, CSP restrittiva, query parametrizzate.
- Rate limiting su login e operazioni sensibili.
- Nessun file privato servito direttamente dal web server.

## Stato del progetto

Attivo e in sviluppo continuo.

## Documentazione

- `PHOTOCARCIFO.MD` — documentazione unificata completa
- `docs/PHOTOCARCIFO.md` — visione e operatività
- `docs/DISASTER_RECOVERY.md` — ripristino completo
