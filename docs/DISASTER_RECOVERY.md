# Disaster recovery — Photo Carcifo

Come rimettere in piedi il sito se il container Proxmox viene perso del
tutto: filesystem locale sparito, NAS Synology ancora vivo, repository
disponibile, backup del database disponibile.

Documento sanitizzato: non contiene nessun valore segreto, solo i nomi
delle chiavi da riempire e dove trovarne i valori.

Ultimo aggiornamento: 03/09/2026. Verificato sul sistema reale (mount,
unit systemd, nginx, restore del database su percorso temporaneo).

---

## 1. Cosa sopravvive e cosa no

| Componente | Dove vive | Sopravvive alla perdita del container? |
|---|---|---|
| Codice applicativo (`app/`, `script/`, `tests/`, `deploy/`, `config/`) | repository git | Sì |
| Fotografie e video | NAS Synology `/volume1/photocarcifo` | Sì |
| Database SQLite | container `data/photocarcifo.db` | **No** — serve il backup |
| Backup database | container `/opt/photocarcifo-db-backup` (14 giorni) + NAS `_backup_sito` (7 giorni, via export) | Solo la copia sul NAS |
| Unit systemd (22 su 27) | container `/etc/systemd/system/` | **No** — serve l'export sul NAS |
| nginx in uso (con TLS, limiti, regole automi) | container `/etc/nginx/sites-available/photocarcifo` | **No** — serve l'export sul NAS |
| `photocarcifo-db-backup.sh` | container `/usr/local/bin/` (file vero, non collegamento) | **No** — serve l'export sul NAS |
| Altri script operativi | collegamenti a `script/` nel repository | Sì |
| `.env` (segreti) | container, `0600` | **No** — i valori vanno dal password manager |
| Credenziali Telegram | container `/etc/photocarcifo-telegram.conf`, `0600` root | **No** — dal password manager |
| Password admin + segreto 2FA | tabella `users` **dentro il database** | Sì, se si ha il backup del database |
| Certificati TLS | container `/etc/letsencrypt/` | Non serve salvarli: si rigenerano con certbot |
| Miniature in cache | container `data/cache/` | Non serve: si rigenerano da sole |

**I veri punti di rottura** sono quindi tre: il database, le unit systemd
e la configurazione nginx. I primi due sono coperti dall'export sul NAS
(`photocarcifo-export-config.sh`); il terzo pure.

---

## 2. Prima di cominciare — cosa serve avere in mano

1. Accesso al NAS Synology (`192.168.1.11`, share `/volume1/photocarcifo`).
2. Il repository git del progetto.
3. Dal password manager: `SECRET_KEY`, `ADMIN_USERNAME`, `INDEXNOW_KEY`,
   token e chat id Telegram. L'elenco completo delle chiavi da riempire
   sta in `_backup_sito/configurazione/env-chiavi.txt` (nomi soltanto).
4. Accesso DNS per `photocarcifo.ch` (serve a certbot).

---

## 3. Procedura

### 3.1 Nuovo container

Ubuntu 24.04 (quello in produzione, con Python 3.12). Su Ubuntu 22.04 le
versioni pinnate in `requirements.txt` vanno riverificate: il venv attuale
è compilato per 3.12.

Rete: IP fisso `192.168.1.206`, raggiungibile dal NAS.

### 3.2 Pacchetti di sistema

```bash
apt-get update
apt-get install -y python3 python3-venv python3-pip nginx nfs-common \
                   ffmpeg sqlite3 certbot python3-certbot-nginx openssl
```

`nfs-common` e `ffmpeg` non sono nel vecchio `deploy/install.sh`: servono,
il primo per montare il NAS, il secondo per le miniature dei video.

### 3.3 Utente di servizio

```bash
useradd --system --home /opt/photocarcifo --shell /usr/sbin/nologin photocarcifo
```

### 3.4 Codice

```bash
git clone <repository> /opt/photocarcifo
cd /opt/photocarcifo
```

### 3.5 Ambiente Python

```bash
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt
# Solo se serve la lettura automatica dei numeri di gara:
./venv/bin/pip install -r requirements-ocr.txt
```

### 3.6 Segreti

```bash
cp .env.example .env
chmod 600 .env
chown photocarcifo:photocarcifo .env
```

Riempire i valori presi dal password manager. `.env.example` documenta
ogni chiave; `_backup_sito/configurazione/env-chiavi.txt` elenca quelle
effettivamente in uso al momento dell'ultimo export.

Credenziali Telegram in `/etc/photocarcifo-telegram.conf` (`chmod 600`,
proprietario root): l'elenco delle chiavi è in
`_backup_sito/configurazione/telegram-chiavi.txt`.

### 3.7 Mount del NAS

**Attenzione**: `deploy/install.sh` monta ancora via CIFS/SMB con un file
di credenziali. Il sistema reale usa NFSv4 senza credenziali. Vale questo,
non lo script:

```bash
mkdir -p /mnt/magazzino /mnt/magazzino-rw
```

In `/etc/fstab` (le stesse righe sono salvate in
`_backup_sito/configurazione/fstab-magazzino.txt`):

```
192.168.1.11:/volume1/photocarcifo  /mnt/magazzino     nfs4  ro,_netdev,soft  0  0
192.168.1.11:/volume1/photocarcifo  /mnt/magazzino-rw  nfs4  rw,_netdev,soft  0  0
```

```bash
mount -a
mountpoint -q /mnt/magazzino && echo "mount ok"
ls /mnt/magazzino | head
```

Il controllo con `mountpoint` non è un dettaglio: una cartella vuota al
posto del mount passerebbe un semplice `ls` senza errori, e lo scanner la
leggerebbe come "tutte le fotografie sono sparite" (vedi
PROJECT_KNOWLEDGE.md §12, resilienza NAS).

### 3.8 Ripristino del database

```bash
mkdir -p /opt/photocarcifo/data
# Dalla copia sul NAS (la più recente):
cp /mnt/magazzino/_backup_sito/photocarcifo-<data>.sqlite \
   /opt/photocarcifo/data/photocarcifo.db
chown photocarcifo:photocarcifo /opt/photocarcifo/data/photocarcifo.db
chmod 640 /opt/photocarcifo/data/photocarcifo.db
```

Verificare **prima** di avviare il servizio:

```bash
sqlite3 /opt/photocarcifo/data/photocarcifo.db 'PRAGMA integrity_check;'
sqlite3 /opt/photocarcifo/data/photocarcifo.db \
  'SELECT COUNT(*) FROM nodes; SELECT COUNT(*) FROM media; SELECT COUNT(*) FROM users;'
```

`integrity_check` deve dire `ok` e `users` deve contenere almeno una riga
(è lì che stanno la password dell'amministratore e il segreto 2FA).

### 3.9 Cartelle dati e permessi

```bash
mkdir -p /opt/photocarcifo/data/{cache,logs,zip-lock}
chown -R photocarcifo:photocarcifo /opt/photocarcifo
chmod 600 /opt/photocarcifo/.env
```

Le miniature in `data/cache/` non vanno ripristinate: si rigenerano alla
prima visita di ogni pagina (il primo giro è più lento, poi torna normale;
`photocarcifo-pregen` le prepara comunque di notte).

### 3.10 Unit systemd

```bash
cp /mnt/magazzino/_backup_sito/configurazione/systemd/photocarcifo*.service \
   /mnt/magazzino/_backup_sito/configurazione/systemd/photocarcifo*.timer \
   /etc/systemd/system/
systemctl daemon-reload
```

Le 5 unit principali (`photocarcifo`, `-scan`, `-numeri` e relativi timer)
stanno anche in `deploy/` nel repository; le altre 22 solo nell'export.

Verifica prima di abilitare:

```bash
systemd-analyze verify /etc/systemd/system/photocarcifo*.service
```

### 3.11 Script fuori repository

```bash
cp /mnt/magazzino/_backup_sito/configurazione/script/* /usr/local/bin/
chmod +x /usr/local/bin/photocarcifo-*
```

Poi ricreare i collegamenti agli script del repository:

```bash
for f in /opt/photocarcifo/script/photocarcifo-*; do
    ln -sf "$f" "/usr/local/bin/$(basename "$f")"
done
```

(I collegamenti non sovrascrivono i file veri già copiati sopra, perché
hanno nomi diversi: l'unico file vero è `photocarcifo-db-backup.sh`.)

### 3.12 nginx

```bash
cp /mnt/magazzino/_backup_sito/configurazione/nginx/photocarcifo \
   /etc/nginx/sites-available/photocarcifo
mkdir -p /etc/nginx/snippets
cp /mnt/magazzino/_backup_sito/configurazione/nginx/snippets/*.conf /etc/nginx/snippets/
ln -sf /etc/nginx/sites-available/photocarcifo /etc/nginx/sites-enabled/photocarcifo
rm -f /etc/nginx/sites-enabled/default
```

La configurazione salvata contiene già i riferimenti ai certificati: fino
a che certbot non li ha creati, `nginx -t` fallirà. Due strade: creare
prima i certificati (passo successivo) oppure commentare temporaneamente
le righe `ssl_certificate`.

### 3.13 Certificati TLS

```bash
certbot --nginx -d photocarcifo.ch -d pannello.photocarcifo.ch
nginx -t && systemctl reload nginx
```

Il DNS deve già puntare al nuovo indirizzo, altrimenti la verifica fallisce.

### 3.14 Avvio

```bash
systemctl enable --now photocarcifo.service
systemctl enable --now photocarcifo-scan.timer photocarcifo-numeri.timer \
    photocarcifo-monitor.timer photocarcifo-db-backup.timer \
    photocarcifo-covers.timer photocarcifo-notte.timer \
    photocarcifo-errori.timer photocarcifo-pregen.timer \
    photocarcifo-rapporto.timer photocarcifo-mensile.timer \
    photocarcifo-sentinella.timer photocarcifo-bot-whitelist.timer
systemctl enable --now photocarcifo-bot.service
```

`photocarcifo-update.timer` resta disabilitato, come in produzione.

### 3.15 Controlli finali

```bash
systemctl status photocarcifo --no-pager
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/healthz
mountpoint -q /mnt/magazzino && echo "NAS ok"
sqlite3 /opt/photocarcifo/data/photocarcifo.db 'SELECT COUNT(*) FROM nodes;'
systemctl list-timers 'photocarcifo*' --no-pager
```

Dal browser: home, un album pubblico, una miniatura, un download, un
album privato (deve chiedere la password), il pannello `/admin` con 2FA.

**Non lanciare subito uno scan completo.** Prima verificare che il mount
sia davvero attivo: con il NAS non montato lo scanner si ferma da solo
(protezione introdotta il 03/09/2026), ma è meglio non metterlo alla prova
durante un ripristino.

---

## 4. RPO e RTO

**RPO — quanti dati si possono perdere.** Fino a **24 ore** di modifiche
al database: il backup gira una volta al giorno alle 03:00, e l'export
verso il NAS lo segue. In pratica si perdono i cambiamenti fatti dal
pannello dopo l'ultimo backup (descrizioni, copertine, album resi privati,
numeri di gara corretti a mano, link di condivisione creati). Le
fotografie non si perdono mai: stanno sul NAS. Uno scan successivo
reindicizza qualunque cartella aggiunta nel frattempo.

**RTO — quanto tempo per tornare online.** Stima realistica **2–4 ore**
lavorando con questo documento davanti: circa 30 minuti per container e
pacchetti, 15 per codice e ambiente Python, 15 per segreti e mount, 10 per
il database, 20 per systemd e nginx, 15 per i certificati (più l'attesa
della propagazione DNS se cambia l'indirizzo), il resto per i controlli.
Va aggiunto il primo giro di miniature, che rallenta le pagine per qualche
ora ma non impedisce l'uso del sito.

Senza questo documento e senza l'export delle configurazioni, la stima
realistica sarebbe di un paio di giorni: 22 unit systemd e una
configurazione nginx cresciuta a mano non si riscrivono a memoria.

---

## 5. Manutenzione di questo piano

- `photocarcifo-export-config.sh` gira ogni notte alle 03:30 (timer
  `photocarcifo-export-config.timer`, dopo il backup del database delle
  03:00). Lo script e le sue unit sono anche in `deploy/` nel repository,
  come riferimento: l'installazione reale resta pero' su
  `/usr/local/bin/` e `/etc/systemd/system/`, l'unica che il timer usa
  davvero. Si puo' anche lanciare a mano dopo una modifica a unit
  systemd, nginx o script fuori repository, invece di aspettare la notte:
  `sudo /usr/local/bin/photocarcifo-export-config.sh`, poi controllare
  `/var/log/photocarcifo-export-config.log`.
- Questo documento va riletto quando cambia il modo di montare il NAS,
  la versione di Ubuntu o l'elenco dei timer.
- `deploy/install.sh` è **disallineato** (monta via CIFS/SMB, dichiara
  Ubuntu 22.04, non installa `nfs-common` né `ffmpeg`, copia solo 5 unit
  su 27): serve per una prima installazione da zero, non per un
  ripristino. In caso di dubbio vale questo documento.
