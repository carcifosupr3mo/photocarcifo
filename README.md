# Photocarcifo

Portfolio fotografico e galleria clienti self-hosted, in produzione con clienti reali.

Le fotografie restano sempre sul NAS di archiviazione (montato in sola lettura); il sito le indicizza e le serve senza mai copiarle nel container applicativo.

## Indice

- [Funzionalità](#funzionalità)
- [Stack](#stack)
- [Architettura](#architettura)
- [Installazione](#installazione-development)
- [Configurazione](#configurazione)
- [Utilizzo](#utilizzo)
- [Ricerca per numero di gara](#ricerca-per-numero-di-gara)
- [Test](#test)
- [Prestazioni](#prestazioni)
- [Deployment](#deployment)
- [Sicurezza](#sicurezza)
- [Backup](#strategia-di-backup)
- [Stato del progetto](#stato-del-progetto)

## Funzionalità

- **Isolamento per album**: un cookie firmato dà accesso a un singolo album e al suo sottoalbero, mai in modo cumulativo tra album diversi, con scadenza del link scelta da chi lo genera.
- **Preferiti clienti**: ogni visitatore può segnare le foto che preferisce; l'admin vede le scelte per album e per persona, con download dedicato.
- **Due modalità di visualizzazione galleria**, correzione automatica della rotazione EXIF su decine di migliaia di scatti storicamente mal orientati.
- **Ricerca per numero di gara**: lettura OCR automatica delle tabelle nelle foto sportive, con correzione manuale che non viene mai sovrascritta dalle letture successive (dettagli [più sotto](#ricerca-per-numero-di-gara)).
- **Rigenerazione notturna delle miniature** su tre formati, backup a rotazione con ripristino automatico in caso di errore e controllo dello spazio libero prima di partire.
- **Report settimanale via email**, mappa del sito generata automaticamente.
- **Cinque lingue**, pagine di errore dedicate, cestino con ripristino (nessuna cancellazione diretta).
- **PageSpeed 100**: CSS critico inline, `fetchpriority` sull'immagine LCP, gerarchia dei titoli corretta.
- **Nessun JavaScript inline**: compatibile con una Content-Security-Policy restrittiva.

## Stack

`Python` · `FastAPI` · `SQLite` · `Jinja2` · `Nginx` · `systemd`

Nessun framework frontend: JavaScript vanilla, CSS scritto a mano. Le miniature sono servite in WebP ai browser che lo dichiarano e in JPEG agli altri, con la cache di Nginx che distingue le due versioni.

## Architettura

```
photocarcifo/
├── app/
│   ├── main.py           # avvio, strati comuni (lingua, sicurezza, errori)
│   ├── config.py         # impostazioni lette da .env
│   ├── database.py       # SQLite: schema, migrazioni, statistiche
│   ├── security.py       # password, sessioni, CSRF, conteggio tentativi
│   ├── deps.py            # utente corrente, permessi, indirizzo del visitatore
│   ├── templating.py     # funzioni disponibili nelle pagine (traduzioni, asset…)
│   ├── lingue*.py         # testi del sito in cinque lingue
│   ├── scanner.py        # legge l'archivio e aggiorna l'indice
│   ├── thumbnails.py     # miniature: misure, formati, copyright incorporato
│   ├── numeri.py          # ricerca per numero di gara
│   ├── ocr.py              # lettura automatica dei numeri dalle fotografie
│   ├── cli.py              # comandi da riga di comando
│   ├── routers/            # una per zona del sito (tree, media, admin, …)
│   ├── templates/          # pagine HTML (Jinja2)
│   └── static/              # css, javascript, icone
├── tests/                  # controlli automatici
├── deploy/                 # unità systemd, configurazione nginx di riferimento
├── script/                  # manutenzione, diagnosi, bot di monitoraggio
├── requirements.txt
└── requirements-ocr.txt   # dipendenze della lettura numeri (pesanti, opzionali)
```

Il sito gira su **più processi uvicorn** dietro Nginx. Con un solo processo, una richiesta che genera un'anteprima a piena risoluzione (circa 700 ms) occupa l'unica corsia disponibile finché non è pronta; nel momento peggiore — una galleria condivisa che porta decine di visitatori insieme — l'effetto si sente. La conseguenza architetturale: **niente stato nella memoria del singolo processo**. Il conteggio dei tentativi di accesso falliti e l'avanzamento della lettura OCR vivono nel database o su file condiviso, non in variabili di processo — altrimenti ogni worker vedrebbe un pezzo diverso dello stato.

Le fotografie originali non transitano mai da Python: FastAPI verifica i permessi e delega il trasferimento del file a Nginx tramite `X-Accel-Redirect`, tenendo il lavoro pesante fuori dall'interprete.

## Installazione (development)

Richiede Python 3.11+.

```bash
git clone <url-del-repository>
cd photocarcifo
python3 -m venv venv
venv/bin/pip install -r requirements.txt

cp .env.example .env
# modifica .env: imposta almeno SECRET_KEY, PHOTO_ROOT, ADMIN_PASSWORD

venv/bin/python -m app.cli scan     # indicizza le foto in PHOTO_ROOT
venv/bin/uvicorn app.main:app --reload
```

La lettura automatica dei numeri di gara è opzionale (`requirements-ocr.txt`, alcune centinaia di MB): senza, il sito funziona identico e i numeri si inseriscono a mano.

## Configurazione

Tutta la configurazione passa da variabili d'ambiente — vedi [`.env.example`](.env.example) per l'elenco completo e commentato. Punti principali:

| Variabile | Scopo |
|---|---|
| `SECRET_KEY` | Firma sessioni e cookie. Genera con `openssl rand -hex 32`. |
| `PHOTO_ROOT` | Cartella (montata in sola lettura) con l'archivio fotografico. |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | Credenziali del pannello, da cambiare al primo avvio. |
| `SESSION_MAX_AGE` / `SESSION_MAX_AGE_LUNGO` | Durata sessione normale e "resta collegato". |
| `RATE_LIMIT_LOGIN` | Tentativi di accesso consentiti prima del blocco temporaneo. |
| `OCR_*` | Soglie della lettura automatica dei numeri (vedi sezione dedicata). |

Il file rifiuta variabili non previste: un refuso in `.env` blocca l'avvio invece di essere ignorato silenziosamente.

## Utilizzo

Pannello amministrativo su `/admin`: gestione album (rinomina, privacy, scadenze link, copertina), caricamento foto, cestino con ripristino, statistiche, richieste di contatto, correzione manuale dei numeri di gara.

Mettere in servizio una modifica al codice non è un semplice riavvio: c'è uno script dedicato che controlla sintassi, test e configurazione nginx *prima* di riavviare, perché i template si rileggono dal disco a ogni richiesta ma il codice Python solo al riavvio — modificare un template prima del codice che lo usa manda in errore tutte le pagine per il tempo che passa fra le due modifiche.

## Ricerca per numero di gara

Un pilota che corre con il numero 198 lo scrive nella barra di ricerca e ottiene tutte le fotografie in cui quel numero compare. Funzionano anche `#198` e `n. 198`; gli zeri iniziali non contano.

**Lettura automatica.** RapidOCR legge le tabelle nelle fotografie, partendo dalla miniatura grande già in cache quando disponibile. Gira su un timer periodico e tocca solo le foto nuove o modificate. Le tabelle si distinguono dal resto del testo in foto (sponsor, marchi, striscioni) perché sono fatte di sole cifre: si scartano automaticamente gli anni (1900–2099) e le cifre singole nelle cartelle dove rappresentano altro (es. numeri di corsia in atletica). Le soglie di confidenza sono state tarate su un campione reale, non a intuito — sotto 0.95 le letture cominciano a sbagliare sistematicamente.

**Correzione manuale.** Dal pannello, per ogni foto: quello che viene scritto a mano non viene mai sovrascritto dalle letture automatiche successive.

**Ripartenza automatica.** L'avanzamento vive nel database, non in memoria: un riavvio del container riprende esattamente da dove si era interrotto, senza perdere lavoro né rileggere da capo.

## Test

```bash
venv/bin/python -m pytest tests -q
```

I test girano contro l'applicazione vera, con accesso in sola lettura ai dati: nessun test scrive o cancella. Coprono le pagine in tutte le lingue supportate, i permessi del pannello, gli album riservati, le pagine di errore, e — il controllo più utile — verificano strutturalmente che nessuna rotta che modifica dati possa esistere senza controllo dei permessi e token anti-CSRF: copiare una rotta esistente dimenticando quel controllo fa fallire i test immediatamente.

## Prestazioni

Alcune misure prese sul sito reale, non stimate:

- Query di ordinamento della home riscritta per evitare una subquery su tutte le fotografie ad ogni visita: **68 ms → 3,6 ms**.
- Ricerca della copertina album passata da scansione dell'intero indice a lettura diretta nella cartella: pagina più pesante da **14 ms a 0,13 ms**.
- CSS critico inlineato nella prima pagina vista, poi servito da cache browser (30 giorni) dalla seconda in poi: **16,5 KB → 3,9 KB** per chi torna.
- Generazione miniature: da 6 letture separate dello stesso originale a una sola condivisa, **3.066 ms → 1.696 ms** a fotografia.
- Formato immagini: introdotto WebP con fallback JPEG automatico via header `Accept` — cache generata scesa da **27,7 GB a 6,7 GB**.

## Deployment

Il repository include, come riferimento generico da adattare al proprio ambiente:

- `deploy/*.service`, `deploy/*.timer` — unità systemd (applicazione, scansione, lettura numeri)
- `deploy/nginx.conf` — configurazione Nginx (reverse proxy, cache miniature, `X-Accel-Redirect` per gli originali)
- `deploy/install.sh` — script di installazione su Ubuntu Server

Non sono pensati per essere copiati alla lettera: vanno adattati a percorsi, utenti di sistema e hardening specifici del proprio ambiente. Questo repository descrive **come** è costruito il sito, non **dove** gira l'istanza in produzione — indirizzi, hostname e topologia di rete restano fuori di proposito.

## Sicurezza

- Password con Argon2, sessioni firmate, CSRF su ogni rotta che modifica dati.
- Verifica in due passaggi (TOTP) per il pannello amministrativo, con contatore separato dal login.
- Rate limiting sui tentativi di accesso, indipendente dal numero di processi applicativi.
- Gli album privati non compaiono mai in homepage, ricerca o sitemap; i link scaduti smettono di funzionare.
- Nessuna credenziale, chiave o dato infrastrutturale è presente in questo repository: la configurazione reale vive solo in un `.env` locale, mai versionato. Vedi [SECURITY.md](SECURITY.md) per la policy di segnalazione vulnerabilità.

## Strategia di backup

In produzione: rotazione di backup del database su più slot, con verifica dello spazio libero prima di ogni copia e ripristino automatico se una copia risulta corrotta. Le fotografie originali vivono solo sull'archivio NAS, che ha la propria strategia di ridondanza indipendente dall'applicazione. Questo repository contiene solo codice sorgente: nessun dato applicativo, backup o log è incluso o va incluso.

## Stato del progetto

In produzione, con clienti reali, dal 2026. Sviluppato e mantenuto da una sola persona. Il codice qui pubblicato è lo stesso in produzione, meno la configurazione specifica dell'installazione (vedi [Sicurezza](#sicurezza)).

---

Vedi anche [SECURITY.md](SECURITY.md) per la segnalazione responsabile di vulnerabilità.
