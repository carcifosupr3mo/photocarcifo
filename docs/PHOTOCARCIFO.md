# PHOTOCARCIFO — Documentazione del progetto

Portfolio fotografico self-hosted. Serve fotografie sportive da un NAS
Synology attraverso un'applicazione FastAPI in un container Proxmox.

Ultimo aggiornamento: agosto 2026

---

## 1. A cosa serve

Il sito ha due pubblici distinti.

**I clienti** arrivano da un link privato dopo uno shooting: guardano le
proprie fotografie, le scaricano singolarmente o in blocco. Non cercano un
fotografo, hanno già lavorato con lui.

**I visitatori** arrivano dai motori di ricerca o dai social e sfogliano il
portfolio pubblico diviso per disciplina sportiva.

Di conseguenza l'esperienza delle gallerie ha la precedenza su tutto il
resto, e i richiami commerciali restano discreti.

---

## 2. Dove gira

| Cosa | Dove |
|---|---|
| Host virtuale | Proxmox, nodo `pve`, 192.168.1.200 |
| Container | LXC 206 `SITO-PHOTOCARCIFO`, 192.168.1.206, Ubuntu, disco 64 GB |
| Archivio fotografie | Synology `magazzino`, 192.168.1.11 |
| Meteo (servizio separato) | Container 204, porta 8000 |

Il container 206 fa **sia da sito sia da proxy**: riceve le porte 80 e 443
dal router e smista i domini. Il vecchio container 203, che faceva da
proxy con Apache, è stato eliminato.

### Domini

| Dominio | Destinazione |
|---|---|
| `photocarcifo.ch` | il sito (dominio principale) |
| `www.photocarcifo.ch` | il sito |
| `gallery.photocarcifo.ch` | il sito (usato nei vecchi link privati) |
| `meteo.photocarcifo.ch` | proxy verso 192.168.1.204:8000 |
| qualsiasi altro nome | risposta 410, pagina rimossa |

Certificati Let's Encrypt per tutti e quattro, rinnovo automatico
verificato.

### Le fotografie

Stanno **solo** sul NAS, in `/volume1/photocarcifo`. Il container le vede
attraverso due montaggi:

- `/mnt/magazzino` — **sola lettura**, usato per servire il sito
- `/mnt/magazzino-rw` — **lettura e scrittura**, usato solo da upload e cestino

La separazione è voluta: quasi tutto il codice non può modificare nulla.
Solo `upload.py` e `trash.py` usano il secondo percorso, e nessuno dei due
contiene istruzioni di cancellazione — spostano soltanto.

Cartelle ignorate dalla scansione (confronto in minuscolo):
`@eadir`, `pwg_representative`, `#recycle`, `@tmp`, `@sharesnap`,
`_cestino`, `_backup_sito`.

---

## 3. Com'è fatto

### Struttura
### Il database

Due tabelle portanti.

**`nodes`** — ogni cartella del NAS è un nodo dell'albero.

| Campo | Significato |
|---|---|
| `parent_id` | nodo superiore, vuoto per le categorie |
| `slug` | indirizzo web, es. `bmx` |
| `rel_path` | percorso reale sul NAS |
| `title` | nome mostrato (modificabile senza toccare il NAS) |
| `is_private` | album riservato, raggiungibile solo col link |
| `access_token` | codice del link privato |
| `password_hash` | password opzionale dell'album |
| `expires_at` | scadenza del link, vuoto = illimitato |
| `hidden` | escluso dal sito, resta gestibile dal pannello |
| `downloads_enabled` | permette o blocca il download |
| `cover_media_id` | fotografia di copertina |
| `direct_media` / `total_media` | conteggi, diretti e dell'intero sottoalbero |

**`media`** — ogni fotografia o filmato, legato al suo nodo.

Poi `users` (con i campi per la verifica in due passaggi), `settings`,
`logs`, `stats`.

Modalità WAL attiva: letture e scritture non si bloccano a vicenda.

---

## 4. Chi può vedere cosa

È la parte più delicata del progetto. La regola sta in `_can_access()`
dentro `media.py` e vale per **ogni** contenuto: miniature, anteprime,
download, filmati, archivi ZIP.

1. **L'amministratore** vede sempre tutto.
2. **I contenuti nascosti** non sono mai accessibili al pubblico.
3. **I link scaduti** non danno più accesso a nulla.
4. **Gli album privati** richiedono il lasciapassare, che si ottiene
   aprendo il link (e superando la password, se impostata).
5. **Tutto il resto** è pubblico.

Il lasciapassare è un cookie firmato che vale ventiquattro ore e copre
l'album **e tutte le sue sottocartelle** — senza questo, le gallerie con
sottocartelle mostrerebbero riquadri vuoti.

> **Attenzione per il futuro.** Se aggiungi una rotta che serve un file,
> deve chiamare `_can_access()`. Le due falle trovate in passato nascevano
> entrambe da questa dimenticanza: bastava indovinare un numero per
> scaricare le fotografie di uno shooting privato.

Nginx esclude dalla cache condivisa chi possiede il lasciapassare,
altrimenti la prima risposta verrebbe servita a chiunque.

---

## 5. Cosa succede da solo

| Orario | Cosa fa |
|---|---|
| 01:00 – 04:15 | prepara le miniature mancanti (tre misure) |
| 04:33 | aggiorna il sistema, salva il database, rilegge il NAS, ottimizza, riavvia e verifica |
| 05:00 | cambia le copertine degli album pubblici |
| variabile | rilettura incrementale del NAS |

La preparazione delle miniature si ferma da sola se lo spazio libero
scende sotto i 6 GB. Il salvataggio del database resta 14 giorni nel
container e 60 sul NAS.

---

## 6. Se qualcosa va storto

### Il sito non risponde

```bash
systemctl status photocarcifo
journalctl -u photocarcifo -n 40 --no-pager
systemctl restart photocarcifo
```

Se non riparte, quasi sempre è `.env`: `config.py` rifiuta le variabili
non dichiarate. `PHOTO_ROOT_RW` in particolare **non va messo lì** — i
moduli lo leggono dall'ambiente con un valore predefinito.

### Errore 502

L'applicazione è caduta, Nginx è in piedi. Guarda il registro sopra: di
solito è un errore di sintassi o un import sbagliato dopo una modifica.

### Chiuso fuori dal pannello

```bash
sqlite3 /opt/photocarcifo/data/photocarcifo.db \
  "UPDATE users SET totp_enabled=0, totp_secret=NULL;"
```

Disattiva la verifica in due passaggi. Entri con la sola password e la
riattivi.

### Le foto private non caricano

Controlla che aprire il link rilasci il lasciapassare:

```bash
curl -sk -c /tmp/ck.txt -o /dev/null https://photocarcifo.ch/p/TOKEN
grep -c pc_unlock /tmp/ck.txt   # deve dare 1
```

### Verifica generale

```bash
/usr/local/bin/photocarcifo-diagnosi.sh
```

Prova ogni tipo di contenuto dal punto di vista di chi ha diritto e di chi
no. Da lanciare dopo ogni modifica.

### Ripristinare il database

```bash
systemctl stop photocarcifo
cp /opt/photocarcifo/backup/db-AAAA-MM-GG.sqlite \
   /opt/photocarcifo/data/photocarcifo.db
chown photocarcifo:photocarcifo /opt/photocarcifo/data/photocarcifo.db
systemctl start photocarcifo
```

Le fotografie non sono nel database: si perde solo l'indice, che si
ricostruisce rileggendo il NAS.

---

## 7. Regole di lavoro

Queste nascono da errori realmente commessi.

**Svuota sempre la cache di Python** prima di riavviare, altrimenti gira
il codice vecchio:

```bash
find /opt/photocarcifo/app -name '__pycache__' -type d -exec rm -rf {} +
```

**Verifica la sintassi prima di riavviare:**

```bash
cd /opt/photocarcifo
./venv/bin/python -c "import ast; ast.parse(open('app/routers/tree.py').read())"
```

**Riscrivi i file interi invece di applicare correzioni parziali.** Le
sostituzioni di testo falliscono in silenzio quando il file è già stato
modificato, e non te ne accorgi finché qualcosa non si rompe.

**Il terminale trasforma `www.` in un link.** Se incolli configurazioni
che lo contengono, il file si riempie di parentesi quadre. Usa uno script
Python che lo scriva, senza digitarlo.

**Prova sempre da fuori casa.** Molti router non permettono di
raggiungere il proprio indirizzo pubblico dall'interno: usa i dati mobili
del telefono.

**`curl -I` restituisce 405.** L'applicazione non accetta richieste HEAD:
usa `curl -o /dev/null`.

---

## 8. Salvataggi

| Cosa | Dove | Ogni quanto |
|---|---|---|
| Container 206 | Proxmox | automatico |
| Fotografie | Synology verso disco esterno | automatico |
| Database | container e NAS | ogni notte |

> Un salvataggio non provato non è un salvataggio. Almeno una volta
> recupera una singola fotografia dal backup e verifica che si apra.

Copia completa del progetto:

```bash
tar -czf /root/photocarcifo-$(date +%F).tar.gz -C /opt photocarcifo \
  --exclude='venv' --exclude='__pycache__' --exclude='data/cache' --exclude='backup'

tar -czf /root/config-sistema-$(date +%F).tar.gz \
  /etc/nginx/sites-available /etc/systemd/system/photocarcifo* \
  /usr/local/bin/photocarcifo-*
```

---

## 9. Cosa non c'è, e perché

**Rinomina delle cartelle sul NAS.** Il pannello cambia solo il nome
mostrato. Rinominare i percorsi reali da un'applicazione web è un rischio
che non vale il comodo: si fa da File Station.

**Riconoscimento dei numeri di gara.** Su fotografie d'azione si
riconoscerebbe circa metà dei numeri, e chi cerca senza trovare se ne va
più insoddisfatto di prima.

**Riconoscimento dei volti.** Si tratterebbero dati biometrici di minori
in contesto sportivo: gli obblighi legali superano il beneficio.

**Vendita di stampe.** Aggiungerebbe pagamenti e fatturazione a un sistema
gestito da una persona sola.

**Miniature WebP.** Il guadagno non giustifica la rigenerazione delle
141.000 immagini già pronte.

---

## 10. Cosa manca davvero

In ordine di utilità.

**Preferiti del cliente.** Il cliente segna le fotografie che vuole, tu
vedi la lista nel pannello. Elimina lo scambio di messaggi con i nomi dei
file, che è l'attrito reale del lavoro quotidiano.

**Statistiche del link privato.** Sapere se il cliente ha aperto la
galleria, quante volte, quante fotografie ha scaricato. I dati sono già
registrati: manca solo mostrarli.

**Condivisione della singola fotografia.** Oggi si condivide solo l'album
intero. Poter mandare a un atleta il suo scatto è il modo naturale in cui
il lavoro si diffonde.

---

## Riferimenti rapidi

```bash
# stato generale
/usr/local/bin/photocarcifo-diagnosi.sh

# avanzamento miniature
cd /opt/photocarcifo && ./venv/bin/python -c "
import sqlite3, shutil
from pathlib import Path
c = sqlite3.connect('data/photocarcifo.db')
foto = c.execute('SELECT COUNT(*) FROM media m JOIN nodes n ON n.id=m.node_id WHERE n.hidden=0').fetchone()[0]
fatti = sum(1 for _ in Path('data/cache/thumbnails').rglob('*.jpg'))
print(f'{fatti} su {foto*3} ({fatti*100//max(foto*3,1)}%) — liberi {shutil.disk_usage(\"/\").free/1024**3:.1f} GB')"

# quante fotografie
sqlite3 /opt/photocarcifo/data/photocarcifo.db "SELECT COUNT(*) FROM media;"

# rilettura del NAS
systemctl start photocarcifo-scan.service

# registro della manutenzione notturna
tail -40 /var/log/photocarcifo-update.log

# automatismi
systemctl list-timers 'photocarcifo*' --no-pager
```
