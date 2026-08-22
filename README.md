# Photocarcifo

Portfolio fotografico professionale self-hosted per Proxmox + Synology.
Le foto restano SEMPRE sul NAS (montato in sola lettura); il sito le indicizza
e le serve senza mai copiarle nel container.

## Infrastruttura
- Container Ubuntu Server 22.04 LTS — `192.168.1.206`
- Synology (hostname `magazzino`) — `192.168.1.11`, cartella foto `/volume1/Foto`
- Mount SMB read-only in `/mnt/magazzino`
- Nginx davanti a FastAPI (uvicorn)

## Installazione rapida (Copy & Paste)

Carica l'intera cartella `photocarcifo/` nel container (es. in /root/), poi:

```bash
cd /root/photocarcifo
chmod +x deploy/install.sh
sudo ./deploy/install.sh
```

Lo script installa dipendenze, crea l'utente di servizio, il virtualenv,
configura il mount SMB, i servizi systemd e Nginx.

## Dopo l'installazione

1. Inserisci le credenziali del NAS:
   ```bash
   sudo nano /etc/photocarcifo-smb.cred
   sudo mount -a
   ```
2. Imposta la password admin:
   ```bash
   sudo nano /opt/photocarcifo/.env      # modifica ADMIN_PASSWORD
   sudo systemctl restart photocarcifo
   ```
3. Prima scansione del NAS:
   ```bash
   sudo systemctl start photocarcifo-scan.service
   ```

## Accesso
- Sito pubblico: http://192.168.1.206
- Dashboard admin: http://192.168.1.206/admin

## Struttura del progetto

```
photocarcifo/
├── app/
│   ├── main.py           # avvio, strati comuni (lingua, sicurezza, errori)
│   ├── config.py         # impostazioni lette da .env
│   ├── database.py       # SQLite: schema, migrazioni, statistiche
│   ├── security.py       # password, sessioni, CSRF, conteggio tentativi
│   ├── deps.py           # utente corrente, permessi, indirizzo del visitatore
│   ├── templating.py     # funzioni disponibili nelle pagine (t, lingua, asset…)
│   ├── lingue.py         # tutti i testi del sito in cinque lingue
│   ├── lingue_legale.py  # condizioni d'uso e privacy, per lingua
│   ├── scanner.py        # legge il NAS e aggiorna l'indice
│   ├── thumbnails.py     # miniature: misure, formati, copyright incorporato
│   ├── numeri.py         # ricerca per numero di gara
│   ├── ocr.py            # lettura automatica dei numeri dalle fotografie
│   ├── cli.py            # comandi da riga di comando
│   ├── routers/          # una per zona del sito (tree, media, admin, …)
│   ├── templates/        # pagine HTML
│   └── static/           # css, javascript, icone
├── tests/                # controlli automatici (vedi sotto)
├── data/                 # database e miniature: non finisce in git
├── deploy/               # installazione, nginx, unita di sistema
├── docs/                 # documentazione del progetto
├── requirements.txt      # librerie del sito
└── requirements-ocr.txt  # librerie della lettura numeri (pesanti, opzionali)
```

## Mettere in servizio una modifica

Non riavviare a mano. C'e' un comando che controlla prima e riavvia dopo:

```bash
photocarcifo-applica.sh            # controlla, riavvia, verifica
photocarcifo-applica.sh --prova    # controlla soltanto
```

Esegue nell'ordine: sintassi del codice, avanzi inutilizzati, sintassi del
JavaScript, caricamento dell'applicazione, tutti i test, configurazione di
nginx. Solo se passa tutto riavvia, e poi verifica dal vivo che dodici
indirizzi rispondano. Se qualcosa non torna il sito resta com'era.

Serve a un errore preciso, gia' successo: i modelli di pagina si rileggono
dal disco a ogni richiesta, il codice solo al riavvio. Modificare un
modello prima del codice che gli serve manda in errore *tutte* le pagine
per il tempo che passa fra le due cose.

## Come gira

Il sito e' servito da **quattro processi** in parallelo (`--workers 4` nel
servizio di sistema). Con un processo solo, una richiesta che si mette a
lavorare — generare un'anteprima a schermo intero costa circa 680
millisecondi — occupava l'unica corsia e chi arrivava aspettava il suo
turno. Misurato: otto anteprime nuove richieste insieme passano da 5,09 a
2,12 secondi.

La conseguenza, che vale la pena ricordare prima di aggiungere codice:
**niente stato nella memoria del processo**. Le richieste di una stessa
persona finiscono su processi diversi. Cio' che deve essere visto da tutti
va nel database (i tentativi di accesso falliti, tabella `tentativi`) o su
file (l'avanzamento della lettura numeri, `data/numeri.stato`). C'e' un
test che se ne accorge se qualcuno riapre quella porta.

## Controlli automatici

```bash
venv/bin/python -m pytest tests -q
```

Girano contro il database vero, in sola lettura: nessun test scrive o
cancella. Coprono le pagine in tutte e cinque le lingue, gli indirizzi
tradotti, i permessi del pannello, gli album riservati, le pagine di
errore, i modelli e le librerie dichiarate.

Il controllo piu' utile e' strutturale: nessuna rotta che modifica dati
puo' esistere senza verifica dei permessi e del token anti-falsificazione.
Una rotta nuova copiata da una vecchia dimenticando il controllo fa
fallire i test subito.

## Note
- Gli album privati non compaiono in homepage, ricerca o sitemap.
- Le miniature si generano quando servono e restano in cache; la
  preparazione notturna anticipa quelle della griglia.
- I caratteri sono quelli di sistema: nessun font da scaricare, quindi
  nessuna attesa e nessuna richiesta a server di terzi.

## Ricerca per numero di gara

Un pilota che corre con la tabella 198 scrive `198` nella barra di ricerca e
ottiene tutte le fotografie in cui quel numero compare. Funzionano anche
`#198` e `n. 198`; gli zeri davanti non contano, quindi `007` e `7` danno lo
stesso risultato. Scrivendo del testo (`verona`, `2024`) la ricerca resta
quella di prima, per cartelle.

Valgono le solite regole di riservatezza: le cartelle nascoste non escono
mai, quelle private solo a chi possiede il link, e i link scaduti non aprono
piu' nulla.

### Da dove arrivano i numeri

1. **Lettura automatica.** RapidOCR legge le tabelle nelle fotografie. Parte
   dalla miniatura grande gia' in cache quando c'e', altrimenti
   dall'originale sul NAS. Gira sui timer di sistema
   (`photocarcifo-numeri.timer`, ogni 15 minuti) e tocca solo le foto nuove
   o modificate.
2. **Correzione a mano.** Nel pannello: Album, si apre una cartella, pulsante
   *Correggi i numeri*. Una casella sotto ogni foto. Quello che si scrive li'
   non viene mai sovrascritto dalle letture successive.

### Come vengono scelti i numeri

In una foto di gara c'e' testo ovunque: striscioni, sponsor, marchi sui
caschi. Le tabelle si riconoscono perche' sono fatte di **sole cifre**:
"heusden", "alecycling.com", "2024 BMX EUROPEAN CUP" contengono lettere e
vengono scartate. Si scartano anche gli anni (1900-2099) e le cifre singole,
che nell'archivio corrispondono ai numeri di corsia sui blocchi di partenza
dell'atletica e ai gradini del podio, non a tabelle.

La dimensione invece conta poco: nelle foto d'azione un pilota lontano ha la
tabella alta l'1% dell'immagine, e una soglia alta le eliminerebbe tutte.

Su un campione di 30 foto BMX vere il riconoscimento trova un numero in circa
6 foto su 10. Le altre sono premiazioni, riprese da dietro, primi piani o
piloti troppo lontani: li' il numero si mette a mano.

### Comandi

```bash
cd /opt/photocarcifo
sudo -u photocarcifo venv/bin/python -m app.cli numeri          # una passata
sudo -u photocarcifo venv/bin/python -m app.cli numeri --all    # tutta la coda
sudo -u photocarcifo venv/bin/python -m app.cli numeri --reset  # rilegge tutto
```

Le soglie si regolano dal `.env` (vedi `.env.example`). Dopo averle cambiate
serve un `--reset` perche' abbiano effetto sulle foto gia' lette.

Il motore di lettura e' opzionale (`requirements-ocr.txt`): senza, il sito
funziona identico e i numeri si scrivono solo a mano.

### Precisione e taratura

Le soglie sono state tarate guardando le fotografie vere, non a intuito:

- **`OCR_MIN_CONFIDENCE=0.95`** — sotto questo valore le letture sono quasi
  tutte sbagliate: un 377 letto come 371, numeri inventati su foto di
  premiazione dove non c'e' nessuna tabella, cifre pescate dalle scritte
  delle maglie. Sopra 0.95 sono affidabili. Un numero sbagliato fa doppio
  danno: sporca la ricerca di un pilota e nasconde quella di un altro.
- **`OCR_MIN_HEIGHT_RATIO=0.008`** — deve restare bassa: nelle foto d'azione
  i piloti lontani hanno tabelle alte l'1% dell'immagine.
- **`OCR_MIN_DIGITS=1`** — le tabelle da 1 a 9 esistono e vanno trovate.
- **`OCR_NIENTE_CIFRE_SINGOLE=ATLETICA`** — nelle cartelle elencate qui le
  cifre singole vengono ignorate: nell'atletica sono i numeri di corsia
  stampati sui blocchi di partenza, letti con sicurezza 0.98-1.00, che
  nessuna soglia riesce a distinguere da una tabella. Li' i pettorali sono
  comunque a tre cifre, quindi non si perde nulla.
- **`OCR_PRIORITA=BMX`** — si parte dalle gare con le tabelle invece di
  seguire l'ordine dell'archivio, e dentro ogni gruppo dalle foto piu'
  recenti.

Cambiando le soglie serve `python -m app.cli numeri --reset` per rileggere
tutto con i nuovi valori.


### Ripartenza automatica

L'avanzamento della lettura sta nel database (colonna `media.ocr_stato`),
non in memoria. Se il container si riavvia o viene aggiornato, il lavoro
riprende esattamente da dove era arrivato:

- `photocarcifo-numeri.service` parte da solo all'avvio del container
  (`WantedBy=multi-user.target`) e non prima che l'archivio sia montato
  (`RequiresMountsFor=/mnt/magazzino`);
- `photocarcifo-numeri.timer` ricontrolla ogni 15 minuti se sono arrivate
  foto nuove, e riparte anche dopo uno spegnimento prolungato
  (`Persistent=true`);
- le fotografie rimaste a meta' vengono rimesse in coda appena il lavoro
  riparte, senza aspettare alcuna scadenza;
- un lucchetto su file impedisce che due letture girino insieme: la
  seconda si accorge della prima ed esce subito, invece di dimezzare la
  memoria disponibile.

### Risultati completi

La ricerca per numero e' impaginata (120 fotografie per pagina), non
troncata: anche un numero presente in migliaia di scatti resta consultabile
per intero.

### Cartelli degli impianti

In certi impianti i settori delle tribune sono numerati con cifre grandi e
nitide. L'OCR le legge con la stessa sicurezza di una tabella (0.98-1.00) e
nessuna soglia riesce a distinguerle. Si distinguono pero' da come si
distribuiscono: la tabella di un pilota compare in poche foto della gara,
quelle in cui c'e' lui; un cartello inquadrato di continuo compare in una
grossa fetta delle foto della stessa cartella.

A lettura conclusa, cartella per cartella, viene quindi scartata la cifra
singola presente in piu' del 15% delle fotografie che hanno un numero
(purche' i casi siano almeno 5). Il controllo gira solo sulle cartelle
lette per intero, perche' a meta' i conteggi ingannerebbero, e non tocca
mai i numeri corretti a mano. Nel registro resta scritto cosa e' stato
scartato e perche'.

## Prestazioni

Misure prese sul posto, non a intuito.

- **La home ordinava gli album ricalcolando ogni volta la data dello scatto
  piu' recente**, con una sottoquery su tutte le fotografie: 68 ms a ogni
  visita. Ora la data e' salvata in `nodes.data_foto`, aggiornata dalla
  scansione e dal cestino. La home e' passata a 3,6 ms.
- **La copertina di ogni cartella veniva cercata con un confronto sul
  percorso**, che nessun indice puo' aiutare: SQLite leggeva tutte le
  48.000 fotografie e le ordinava in una tabella temporanea, 8,5 ms per
  cartella mostrata. Ora si guarda prima dentro la cartella stessa, che e'
  una lettura sull'indice: la pagina delle novita' e' passata da 14 ms a
  0,13. Le copertine mostrate sono rimaste le stesse, verificate una per
  una su tutti i nodi.
- **Il foglio di stile viaggiava dentro ogni pagina**, 67 KB che il browser
  non poteva riutilizzare. Ora la prima pagina lo riceve dentro (si disegna
  subito) e lascia un segno; dalla seconda in poi riceve il collegamento,
  che il browser ha in cache per trenta giorni. Una pagina d'album e'
  passata da 16,5 KB a 3,9 KB per chi torna.
- **Le miniature venivano preparate una alla volta**, riaprendo e
  ridecodificando lo stesso originale da 14 MB per ogni copia: sei letture
  dal NAS per sei file. Ora si legge una volta sola: da 3.066 a 1.696 ms a
  fotografia, con i file prodotti identici punto per punto.
- **Il JPEG occupava il 59% della cache** (16,4 GB) e lo riceve solo chi
  non dichiara ne' WebP ne' AVIF, cioe' browser anteriori al 2020. Non si
  prepara piu' in anticipo: chi lo chiede se lo vede generare in mezzo
  secondo. Con l'AVIF aggiunto e l'anteprima grande generata su richiesta,
  la cache e' passata da 27,7 a 6,7 GB.

### Formato delle immagini

Le miniature vengono servite in **WebP** ai browser che lo dichiarano
(intestazione `Accept`) e in JPEG a tutti gli altri: a parita' di resa
visiva il WebP pesa circa il 40% in meno. Sulla home significa 176 KB
scaricati invece di 106.

Due dettagli che rendono la cosa sicura:

- le due scale di qualita' non coincidono. WebP 82 e' indistinguibile da
  JPEG 88 (verificato al doppio dell'ingrandimento sulle fotografie del
  sito) ma pesa il 40% in meno; usare 88 anche sul WebP annullerebbe quasi
  tutto il guadagno;
- la stessa richiesta puo' restituire due file diversi, quindi la risposta
  porta `Vary: Accept` e la cache di Nginx include il formato nella propria
  chiave. Senza, a chi non legge il WebP verrebbero servite immagini vuote.

Le miniature JPEG gia' in cache restano valide: il WebP ha una chiave
propria e i due file convivono. La preparazione notturna li genera
entrambi.

### L'immagine piu' grande della home

La prima scheda della home e' l'elemento su cui i browser misurano il tempo
di caricamento percepito (LCP). Due accorgimenti la riguardano:

- **si carica subito**, con `src` e `fetchpriority="high"`, invece di
  aspettare che parta il JavaScript come le altre. Caricarla in modo pigro
  ritardava proprio l'immagine che conta di piu';
- **usa `/cover/`**, la versione alleggerita gia' prevista dal progetto ma
  mai collegata: stesse dimensioni della miniatura normale, 19 KB invece di
  29. Al doppio dell'ingrandimento le due sono indistinguibili.

Le altre schede restano differite: si caricano mentre il visitatore guarda
la prima.

## Storia delle modifiche

Il progetto e' sotto controllo di versione dal 17/08/2026, sul ramo
`principale`. I comandi si danno come utente del sito, che e' quello che
possiede i file:

```bash
sudo -u photocarcifo git status
sudo -u photocarcifo git log --oneline
sudo -u photocarcifo git diff
```

Restano fuori dal repository, di proposito: `.env` (segreti), `data/`
(database e miniature: stanno nelle copie notturne, non qui), `venv/`, e
tutto cio' che si rigenera da solo — `style.min.css` e `docs/CODICE.md`.

Le copie notturne e il controllo di versione fanno due mestieri diversi e
servono tutti e due: le copie riportano indietro **i dati**, la storia
spiega cosa e' cambiato **nel codice** e perche'.

## I copioni di sistema

Dal 21/08/2026 i copioni che tengono in piedi il sito — messa in servizio,
manutenzione notturna, diagnosi, riparazione, bot Telegram — stanno in
`script/` e non piu' sparsi in `/usr/local/bin`. Li' e' rimasto un
collegamento per ognuno, cosi' i servizi e i timer che li richiamano per
indirizzo assoluto continuano a funzionare senza sapere nulla del
cambiamento.

Il motivo e' semplice: erano fuori dal repository, quindi non avevano
storia. Le copie notturne li salvavano, ma "com'era prima di quella
modifica" non lo sapeva nessuno — proprio per i file che, se si rompono,
portano giu' tutto.

    script/photocarcifo-applica.sh     mette in servizio una modifica
    script/photocarcifo-notte.sh       manutenzione notturna
    script/photocarcifo-diagnosi.sh    i 66 controlli di funzionamento
    script/photocarcifo-ripara.sh      cerca i guasti e ripara i noti
    script/photocarcifo-bot.py         il bot Telegram che risponde

Si modificano qui dentro. Il collegamento in `/usr/local/bin` punta al
file vero: non serve ricopiare niente.

## La configurazione di nginx

Dal 22/08/2026 sta in `config/nginx/`, come i copioni. In `/etc/nginx` e'
rimasto un collegamento, quindi nginx la trova dov'e' sempre stata.

    config/nginx/photocarcifo.conf              il sito
    config/nginx/snippets/photocarcifo-sicurezza.conf   le protezioni
    config/nginx/snippets/photocarcifo-automi.conf      chi passa e chi no

E' il file che decide come viene servito tutto, cambia spesso, e finora
non aveva storia: le copie notturne lo salvavano, ma "cos'e' cambiato
ieri" non lo sapeva nessuno. Si modifica qui dentro, poi
`photocarcifo-applica.sh` lo verifica e lo mette in servizio.

Il `nginx.conf` generale resta dov'e': e' un file della distribuzione,
condiviso con tutto il resto della macchina, e non appartiene a questo
progetto.
