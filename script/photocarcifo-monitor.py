#!/usr/bin/env python3
"""Monitoraggio automatico di PhotoCarcifo: un controllo, non una piattaforma.

Gira ogni 5 minuti via systemd timer e verifica in un colpo solo le cose che,
se si rompono, il sito diventa inutilizzabile o rischioso: il sito pubblico
risponde, il backend locale risponde, nginx e il bot Telegram sono attivi, il
database SQLite non e' corrotto, il disco non sta per riempirsi, la RAM non e'
satura. Se qualcosa non va manda UN avviso su Telegram (riusa il bot
amministrativo gia' configurato, non ne crea uno nuovo); quando torna tutto
normale manda UN avviso di recovery. Mentre il problema persiste, silenzio:
lo stato di ogni controllo viene ricordato in un file JSON locale apposta per
non spammare lo stesso guasto ad ogni giro.

Il sito pubblico e' l'unico controllo per cui un singolo fallimento non basta
a dichiarare un guasto (un timeout isolato capita, per rete o per un riavvio
di pochi secondi): serve 3 fallimenti consecutivi. Tutti gli altri controlli
(systemd, disco, DB) sono gia' affidabili al primo giro: se systemctl dice
che nginx e' fermo, e' fermo davvero, non serve riprovare.
"""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

CONFIG = "/etc/photocarcifo-telegram.conf"
STATO = "/var/lib/photocarcifo/monitor-stato.json"
LOG = "/var/lib/photocarcifo/monitor.log"

URL_PUBBLICO = "https://photocarcifo.ch/healthz"
URL_LOCALE = "http://127.0.0.1:8000/healthz"
DB_PATH = "/opt/photocarcifo/data/photocarcifo.db"
DISCO_PATH = "/opt/photocarcifo/data"          # stesso filesystem del DB e dell'app
LOG_5XX = "/var/log/nginx/photocarcifo-5xx.log"

SERVIZI = ["photocarcifo.service", "nginx.service", "photocarcifo-bot.service"]

TENTATIVI_SITO = 3
PAUSA_TENTATIVI = 10       # secondi fra un tentativo e l'altro sul sito pubblico
TIMEOUT_HTTP = 5           # timeout breve e ragionevole per ogni richiesta

DISCO_WARNING = 15         # % liberi
DISCO_CRITICAL = 8

RAM_WARNING = 90           # % usata, per piu' controlli consecutivi
RAM_CONSECUTIVI = 3        # quanti giri di fila prima di avvisare

SOGLIA_5XX = 5             # errori nella finestra
FINESTRA_5XX_MIN = 5       # minuti

INTEGRITY_CHECK_OGNI_ORE = 24   # controllo pesante del DB una volta al giorno

# Il backup gira ogni notte alle 03:00 (photocarcifo-db-backup.timer). 30
# ore e non 24: RandomizedDelaySec, un riavvio della macchina proprio in
# quella finestra o un giro in ritardo non devono far scattare un allarme
# per un backup che in realta' e' solo di qualche ora piu' vecchio del
# solito — 30 ore lasciano un margine di sei ore oltre il giro
# successivo previsto, abbastanza per assorbire un ritardo senza
# nascondere un backup davvero saltato (che a quel punto avrebbe quasi
# due giorni).
BACKUP_DIR = "/opt/photocarcifo-db-backup"
BACKUP_MAX_ETA_ORE = 30
BACKUP_CHECK_OGNI_ORE = 24   # apertura+integrity_check+conteggi: pesante come sopra

# L'export della configurazione (nginx, fail2ban, systemd, e l'ultima copia
# del backup DB) gira alle 03:30, appena dopo il backup: stessa soglia.
NAS_BACKUP_PATH = "/mnt/magazzino-rw"          # mount in scrittura, diverso
                                                # da /mnt/magazzino (sola
                                                # lettura) gia' controllato
                                                # sotto per lo scanner
EXPORT_CONFIG_DIR = NAS_BACKUP_PATH + "/_backup_sito/configurazione"
EXPORT_MAX_ETA_ORE = 30


# --------------------------------------------------------------- config/log

def leggi_config(percorso=CONFIG):
    valori = {}
    try:
        with open(percorso, encoding="utf-8") as f:
            for riga in f:
                riga = riga.strip()
                if not riga or riga.startswith("#") or "=" not in riga:
                    continue
                chiave, _, valore = riga.partition("=")
                valori[chiave.strip()] = valore.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return valori


def loga(riga):
    try:
        Path(LOG).parent.mkdir(parents=True, exist_ok=True)
        quando = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{quando} {riga}\n")
    except Exception:
        pass


# --------------------------------------------------------------- stato persistente

def leggi_stato():
    try:
        with open(STATO, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def scrivi_stato(stato):
    try:
        Path(STATO).parent.mkdir(parents=True, exist_ok=True)
        tmp = f"{STATO}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(stato, f)
        os.replace(tmp, STATO)
        os.chmod(STATO, 0o600)
    except Exception:
        pass


# --------------------------------------------------------------- notifica Telegram

def invia_telegram(config, testo):
    token = config.get("TELEGRAM_TOKEN")
    chat = config.get("TELEGRAM_CHAT")
    if not token or not chat:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    corpo = urllib.parse.urlencode({
        "chat_id": chat, "text": testo, "parse_mode": "HTML",
    }).encode("utf-8")
    richiesta = urllib.request.Request(url, data=corpo, method="POST")
    try:
        with urllib.request.urlopen(richiesta, timeout=20) as r:
            return r.status == 200
    except Exception as errore:
        loga(f"invio Telegram fallito: {errore}")
        return False


# --------------------------------------------------------------- singoli controlli

def controlla_sito_pubblico():
    """3 tentativi ravvicinati prima di dichiarare il sito giu'. Ritorna
    (ok, dettaglio) dove dettaglio spiega l'ultimo esito (codice o timeout)."""
    ultimo = None
    for tentativo in range(TENTATIVI_SITO):
        try:
            richiesta = urllib.request.Request(URL_PUBBLICO, method="GET")
            inizio = time.monotonic()
            with urllib.request.urlopen(richiesta, timeout=TIMEOUT_HTTP) as r:
                durata = time.monotonic() - inizio
                if r.status == 200:
                    return True, f"200 in {durata:.1f}s"
                ultimo = f"risponde {r.status}"
        except urllib.error.HTTPError as errore:
            ultimo = f"risponde {errore.code}"
        except Exception:
            ultimo = f"timeout dopo {TIMEOUT_HTTP}s"
        if tentativo < TENTATIVI_SITO - 1:
            time.sleep(PAUSA_TENTATIVI)
    return False, ultimo or "nessuna risposta"


def controlla_backend_locale():
    try:
        richiesta = urllib.request.Request(URL_LOCALE, method="GET")
        with urllib.request.urlopen(richiesta, timeout=TIMEOUT_HTTP) as r:
            return r.status == 200, f"{r.status}"
    except urllib.error.HTTPError as errore:
        return False, f"{errore.code}"
    except Exception:
        return False, "non risponde"


def controlla_servizio(nome):
    try:
        r = subprocess.run(["systemctl", "is-active", nome],
                            capture_output=True, text=True, timeout=10)
        stato = r.stdout.strip()
        return stato == "active", stato or "sconosciuto"
    except Exception as errore:
        return False, f"errore: {errore}"


def controlla_db_leggero(percorso=DB_PATH):
    """PRAGMA quick_check: leggero, va bene ad ogni giro. Un database
    momentaneamente locked da una scrittura non e' un guasto: si ritenta
    con un timeout breve invece di allarmare subito."""
    try:
        conn = sqlite3.connect(percorso, timeout=5.0)
        try:
            cur = conn.execute("PRAGMA quick_check")
            risultato = cur.fetchone()
            ok = risultato is not None and risultato[0] == "ok"
            return ok, (risultato[0] if risultato else "nessun risultato")
        finally:
            conn.close()
    except sqlite3.OperationalError as errore:
        if "locked" in str(errore).lower():
            return True, "locked (temporaneo, ignorato)"
        return False, str(errore)
    except Exception as errore:
        return False, str(errore)


def controlla_db_integrita_completa(percorso=DB_PATH):
    """PRAGMA integrity_check: pesante, va fatto solo una volta al giorno."""
    try:
        conn = sqlite3.connect(percorso, timeout=10.0)
        try:
            cur = conn.execute("PRAGMA integrity_check")
            righe = [r[0] for r in cur.fetchall()]
            ok = righe == ["ok"]
            return ok, "ok" if ok else "; ".join(righe[:5])
        finally:
            conn.close()
    except Exception as errore:
        return False, str(errore)


def controlla_nas(percorso="/mnt/magazzino"):
    """Vero solo se il NAS e' realmente montato, non solo se la cartella
    esiste: un NFS che cade lascia il mountpoint locale al suo posto,
    normale cartella (spesso vuota), che .exists() vedrebbe comunque
    come presente. Stessa logica di app.scanner._nas_disponibile."""
    try:
        if not os.path.ismount(percorso):
            return False
        with os.scandir(percorso):
            pass
        return True
    except OSError:
        return False


def _ultimo_backup_db(cartella=BACKUP_DIR):
    """Il file di backup piu' recente nella cartella, o None se non ce ne
    sono. Solo metadata (nome dei file), nessuna apertura: usata sia dal
    controllo leggero sia da quello pesante, cosi' i due concordano
    sempre su QUALE file stanno giudicando."""
    try:
        candidati = sorted(Path(cartella).glob("photocarcifo-*.sqlite"),
                           key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return None
    return candidati[0] if candidati else None


def controlla_backup_db_recente(cartella=BACKUP_DIR, adesso=None):
    """Solo filesystem — un giro su una cartella con 14 file al massimo,
    nessuna apertura del database: costa un attimo, va bene ad ogni giro
    di monitor, a differenza della verifica pesante sotto."""
    adesso = adesso or datetime.now(timezone.utc)
    ultimo = _ultimo_backup_db(cartella)
    if ultimo is None:
        return False, "nessun file di backup trovato"
    try:
        info = ultimo.stat()
    except OSError as errore:
        return False, str(errore)
    if info.st_size == 0:
        return False, f"{ultimo.name} e' vuoto"
    eta_ore = (adesso - datetime.fromtimestamp(
        info.st_mtime, tz=timezone.utc)).total_seconds() / 3600
    if eta_ore > BACKUP_MAX_ETA_ORE:
        return False, f"{ultimo.name} ha {eta_ore:.0f} ore"
    return True, f"{ultimo.name}, {eta_ore:.0f}h fa"


def _ripulisci_copie_orfane():
    """Il 'finally' dentro controlla_backup_db_integrita cancella sempre
    la sua copia — ma solo se il processo Python arriva a girarlo: un
    OOM-killer, un 'systemctl kill' o un riavvio della macchina a meta'
    della copia di 23 MB non lasciano a nessuno la possibilita' di
    ripulire. Con un controllo giornaliero non e' un disastro, ma si
    accumulerebbe zitto — 23 MB alla volta — fino a farsi notare solo
    quando scattasse controlla_disco, che e' proprio uno dei controlli di
    questo file. Un'ora di margine: piu' del previsto anche per un
    backup molto piu' grande di adesso, poco per confondersi con una
    copia che un altro giro ha appena iniziato."""
    UN_ORA = 3600
    adesso = time.time()
    try:
        for percorso in Path(tempfile.gettempdir()).glob(
                "photocarcifo-restore-check-*.sqlite*"):
            try:
                if adesso - percorso.stat().st_mtime > UN_ORA:
                    percorso.unlink()
            except OSError:
                pass
    except OSError:
        pass


def controlla_backup_db_integrita(cartella=BACKUP_DIR, percorso_produzione=DB_PATH):
    """Il test di restore non distruttivo: copia il backup piu' recente
    in un file temporaneo (mai il file di backup originale, mai la
    produzione), lo apre, controlla l'integrita', verifica che le
    tabelle principali esistano e non siano vuote in modo anomalo — poi
    cancella la copia. Se questi passi riescono, il backup non e' solo
    "un file che esiste": e' un database che si puo' davvero riaprire.

    Il confronto con la produzione e' un extra molto prudente (un
    crollo netto dei conteggi, non un limite preciso): serve a
    prendere un backup di un database svuotato per errore, non la
    normale oscillazione quotidiana del numero di foto."""
    ultimo = _ultimo_backup_db(cartella)
    if ultimo is None:
        return False, "nessun file di backup trovato"
    tmp = Path(tempfile.gettempdir()) / f"photocarcifo-restore-check-{os.getpid()}.sqlite"
    try:
        shutil.copy2(ultimo, tmp)
        conn = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True, timeout=10.0)
        try:
            righe = [r[0] for r in conn.execute("PRAGMA integrity_check").fetchall()]
            if righe != ["ok"]:
                return False, f"integrity_check: {'; '.join(righe[:3])}"
            tabelle = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            mancanti = [t for t in ("nodes", "media") if t not in tabelle]
            if mancanti:
                return False, f"tabelle assenti nel backup: {', '.join(mancanti)}"
            nodes = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            media = conn.execute("SELECT COUNT(*) FROM media").fetchone()[0]
            if nodes == 0 or media == 0:
                return False, f"backup vuoto in modo anomalo (nodes={nodes} media={media})"
        finally:
            conn.close()
    except Exception as errore:
        return False, str(errore)
    finally:
        # Se il backup e' in WAL (come il database di produzione da cui
        # nasce), aprirlo crea anche -wal e -shm accanto al file: senza
        # cancellare anche quelli, ogni giro lascia due file in piu' in
        # /tmp — trovato provando il test, non a lettura del codice.
        for suffisso in ("", "-wal", "-shm"):
            try:
                Path(str(tmp) + suffisso).unlink(missing_ok=True)
            except OSError:
                pass

    try:
        conn_prod = sqlite3.connect(f"file:{percorso_produzione}?mode=ro",
                                    uri=True, timeout=5.0)
        try:
            media_prod = conn_prod.execute("SELECT COUNT(*) FROM media").fetchone()[0]
        finally:
            conn_prod.close()
        if media_prod > 0 and media < media_prod * 0.5:
            return False, (f"media nel backup ({media}) molto inferiore "
                           f"alla produzione ({media_prod})")
    except Exception:
        pass  # il confronto e' un extra prudente: se fallisce non e' un motivo di allarme

    return True, f"nodes={nodes} media={media}"


def controlla_export_config(nas_raggiungibile, cartella=EXPORT_CONFIG_DIR, adesso=None):
    """Solo metadata, come il controllo leggero del backup: guarda quando
    e' stato scritto per l'ultima volta env-chiavi.txt (riscritto ad ogni
    esecuzione riuscita dell'export, quindi la sua data e' la data
    dell'ultimo export completato). Se il NAS non risponde il controllo
    non ha niente di attendibile da dire: si salta, cosi' non si manda un
    secondo allarme sopra a quello gia' dedicato al NAS.

    "Saltato" torna None e non True: chi chiama deve poter distinguere
    "verificato, va bene" da "non verificabile ora", altrimenti un export
    gia' scaduto (stato "critico", alert gia' inviato) che smette di
    essere controllabile perche' nel frattempo cade anche il NAS
    produrrebbe un falso "tornato operativo" al giro successivo — il
    problema originale non si e' risolto, si e' solo smesso di vederlo.
    Trovato dalla code review, non da un test."""
    if not nas_raggiungibile:
        return None, "NAS non raggiungibile: controllo saltato"
    adesso = adesso or datetime.now(timezone.utc)
    chiave = Path(cartella) / "env-chiavi.txt"
    try:
        if not chiave.exists():
            return False, "nessun export di configurazione trovato"
        mtime = chiave.stat().st_mtime
    except OSError as errore:
        return False, str(errore)
    eta_ore = (adesso - datetime.fromtimestamp(mtime, tz=timezone.utc)).total_seconds() / 3600
    if eta_ore > EXPORT_MAX_ETA_ORE:
        return False, f"ultimo export ha {eta_ore:.0f} ore"
    return True, f"{eta_ore:.0f}h fa"


def controlla_disco(percorso=DISCO_PATH):
    try:
        uso = shutil.disk_usage(percorso)
        liberi_pct = uso.free / uso.total * 100
        if liberi_pct < DISCO_CRITICAL:
            return "critical", liberi_pct
        if liberi_pct < DISCO_WARNING:
            return "warning", liberi_pct
        return "ok", liberi_pct
    except Exception:
        return "errore", 0.0


def controlla_ram():
    """Percentuale di RAM usata, da /proc/meminfo (nessuna dipendenza esterna)."""
    try:
        valori = {}
        with open("/proc/meminfo", encoding="utf-8") as f:
            for riga in f:
                nome, _, resto = riga.partition(":")
                m = re.match(r"\s*(\d+)", resto)
                if m:
                    valori[nome] = int(m.group(1))
        totale = valori.get("MemTotal", 0)
        disponibile = valori.get("MemAvailable", 0)
        if not totale:
            return 0.0
        usata_pct = (totale - disponibile) / totale * 100
        return usata_pct
    except Exception:
        return 0.0


def conta_5xx_recenti(percorso=LOG_5XX, finestra_minuti=FINESTRA_5XX_MIN):
    """Conta le righe del log 5xx negli ultimi `finestra_minuti` minuti,
    usando l'orario di modifica/lettura del file in modo semplice: si
    guardano solo le ultime righe (il log e' quasi sempre vuoto o corto)
    e si contano quelle con timestamp nginx recente."""
    try:
        if not os.path.exists(percorso) or os.path.getsize(percorso) == 0:
            return 0
        with open(percorso, encoding="utf-8", errors="replace") as f:
            righe = f.readlines()[-3000:]
    except Exception:
        return 0
    ora = datetime.now()
    minuti_accettabili = {
        (ora.replace(microsecond=0) - timedelta(minutes=m)).strftime("%d/%b/%Y:%H:%M")
        for m in range(finestra_minuti + 1)
    }
    quanti = 0
    for riga in righe:
        m = re.search(r"\[(\d{2}/\w{3}/\d{4}:\d{2}:\d{2})", riga)
        if m and m.group(1) in minuti_accettabili:
            quanti += 1
    return quanti


# --------------------------------------------------------------- messaggi

def _ora():
    return datetime.now().strftime("%H:%M")


def costruisci_messaggio_down(dettagli):
    """dettagli: dict con esito di ogni controllo, per distinguere subito
    se il problema e' pubblico/rete, nginx, backend o database."""
    righe = ["🔴 <b>PhotoCarcifo DOWN</b>"]
    righe.append(f"Controllo: HTTPS pubblico")
    righe.append(f"Errore: {dettagli.get('sito_dettaglio', '?')}")
    righe.append(f"Backend locale: {dettagli.get('backend_testo', '?')}")
    righe.append(f"Nginx: {dettagli.get('nginx_testo', '?')}")
    righe.append(f"Ora: {_ora()}")
    return "\n".join(righe)


def costruisci_messaggio_recovery(nome_umano):
    return f"✅ {nome_umano} è tornato operativo\nOra: {_ora()}"


def costruisci_messaggio_warning(titolo, dettaglio):
    return f"⚠️ {titolo}\n{dettaglio}\nOra: {_ora()}"


def costruisci_messaggio_critical(titolo, dettaglio):
    return f"🔴 {titolo}\n{dettaglio}\nOra: {_ora()}"


# --------------------------------------------------------------- anti-spam

def _transizione(stato, chiave, adesso_ok, invia_giu, invia_su):
    """Ricorda lo stato precedente per `chiave`; invia un messaggio SOLO
    al cambio di stato (giu'->su o su->giu'), mai mentre resta invariato.
    Il valore va comunque scritto ad ogni giro (anche quando non cambia):
    altrimenti stato[chiave] resta assente finche' non avviene una vera
    transizione, e chi legge lo stato da fuori (es. /health nel bot) non
    vede mai il valore attuale di un controllo che e' sempre stato sano."""
    prima_ok = stato.get(chiave, {}).get("ok", True)
    if prima_ok != adesso_ok:
        if not adesso_ok:
            invia_giu()
        else:
            invia_su()
    stato.setdefault(chiave, {})["ok"] = adesso_ok


# --------------------------------------------------------------- ciclo principale

def esegui_controlli(config=None, adesso=None):
    """Orchestrazione completa di un giro di monitoraggio. Isolata da
    sys.argv/sys.exit e da time.sleep reale solo tramite i parametri delle
    singole funzioni (i test mockano le funzioni di rete/systemd, non
    questa). Ritorna il nuovo stato (dict) per ispezione nei test."""
    if config is None:
        config = leggi_config()
    stato = leggi_stato()
    adesso = adesso or datetime.now(timezone.utc)

    # Ad ogni giro (ogni 5 minuti) e non solo quando gira il controllo
    # pesante sul backup: legarla al throttle giornaliero significava che
    # in un giorno tranquillo — quello throttled, senza un vero controllo
    # — un residuo lasciato da un processo ucciso a meta' copia poteva
    # restare fino a 24 ore invece del margine di un'ora previsto. Costa
    # un giro su una cartella temp, non un'apertura di database: resta
    # comunque leggero.
    _ripulisci_copie_orfane()

    def avvisa(testo):
        inviato = invia_telegram(config, testo)
        loga(f"notifica inviata={inviato}: {testo.splitlines()[0]}")
        return inviato

    # ---- sito pubblico + backend locale + nginx: un solo evento DOWN combinato
    sito_ok, sito_dettaglio = controlla_sito_pubblico()
    backend_ok, backend_dettaglio = controlla_backend_locale()
    nginx_ok, nginx_dettaglio = controlla_servizio("nginx.service")

    dettagli = {
        "sito_dettaglio": sito_dettaglio,
        "backend_testo": "OK" if backend_ok else f"KO ({backend_dettaglio})",
        "nginx_testo": "OK" if nginx_ok else f"KO ({nginx_dettaglio})",
    }
    _transizione(
        stato, "sito",
        sito_ok,
        lambda: avvisa(costruisci_messaggio_down(dettagli)),
        lambda: avvisa(costruisci_messaggio_recovery("PhotoCarcifo")),
    )

    # ---- servizi applicativi (photocarcifo, bot) — ognuno il proprio stato
    for servizio in ("photocarcifo.service", "photocarcifo-bot.service"):
        ok, dettaglio = controlla_servizio(servizio)
        nome_umano = {
            "photocarcifo.service": "Servizio applicativo",
            "photocarcifo-bot.service": "Bot Telegram",
        }[servizio]
        _transizione(
            stato, servizio,
            ok,
            lambda n=nome_umano, d=dettaglio: avvisa(
                costruisci_messaggio_critical(f"{n} non attivo", f"Stato: {d}")),
            lambda n=nome_umano: avvisa(costruisci_messaggio_recovery(n)),
        )

    # ---- database: quick_check ad ogni giro
    db_ok, db_dettaglio = controlla_db_leggero()
    _transizione(
        stato, "db",
        db_ok,
        lambda: avvisa(costruisci_messaggio_critical(
            "Database non integro", f"quick_check: {db_dettaglio}")),
        lambda: avvisa(costruisci_messaggio_recovery("Database")),
    )

    # ---- integrity_check completo: solo una volta al giorno
    ultimo_integrity = stato.get("db_integrity_check_quando")
    fai_integrity = True
    if ultimo_integrity:
        try:
            passate_ore = (adesso - datetime.fromisoformat(ultimo_integrity)
                           ).total_seconds() / 3600
            fai_integrity = passate_ore >= INTEGRITY_CHECK_OGNI_ORE
        except Exception:
            fai_integrity = True
    if fai_integrity:
        integ_ok, integ_dettaglio = controlla_db_integrita_completa()
        stato["db_integrity_check_quando"] = adesso.isoformat(timespec="seconds")
        _transizione(
            stato, "db_integrity",
            integ_ok,
            lambda: avvisa(costruisci_messaggio_critical(
                "Database - integrity_check fallito", integ_dettaglio)),
            lambda: avvisa(costruisci_messaggio_recovery("Database (integrity_check)")),
        )

    # ---- NAS: un solo alert alla caduta, uno al ritorno, silenzio
    # se resta giu' o resta su fra un giro e l'altro
    nas_ok = controlla_nas()
    _transizione(
        stato, "nas",
        nas_ok,
        lambda: avvisa(costruisci_messaggio_critical(
            "NAS non raggiungibile", "/mnt/magazzino non e' montato o non risponde")),
        lambda: avvisa(costruisci_messaggio_recovery("NAS")),
    )

    # ---- backup database: eta' e dimensione ad ogni giro (solo filesystem)
    backup_ok, backup_dettaglio = controlla_backup_db_recente(adesso=adesso)
    _transizione(
        stato, "backup_db",
        backup_ok,
        lambda: avvisa(costruisci_messaggio_critical(
            "Backup database non valido", backup_dettaglio)),
        lambda: avvisa(costruisci_messaggio_recovery("Backup database")),
    )

    # ---- backup database: apertura + integrity_check + conteggi, una
    # volta al giorno (stesso principio dell'integrity_check di produzione
    # qui sopra: e' un test di restore vero e proprio, non solo uno stat)
    ultimo_backup_integrity = stato.get("backup_db_integrity_quando")
    fai_backup_integrity = True
    if ultimo_backup_integrity:
        try:
            passate_ore = (adesso - datetime.fromisoformat(ultimo_backup_integrity)
                           ).total_seconds() / 3600
            fai_backup_integrity = passate_ore >= BACKUP_CHECK_OGNI_ORE
        except Exception:
            fai_backup_integrity = True
    if fai_backup_integrity:
        integ_backup_ok, integ_backup_dettaglio = controlla_backup_db_integrita()
        stato["backup_db_integrity_quando"] = adesso.isoformat(timespec="seconds")
        _transizione(
            stato, "backup_db_integrity",
            integ_backup_ok,
            lambda: avvisa(costruisci_messaggio_critical(
                "Backup database non ripristinabile", integ_backup_dettaglio)),
            lambda: avvisa(costruisci_messaggio_recovery("Backup database (restore test)")),
        )

    # ---- NAS di scrittura (backup/export): mount diverso da quello sopra,
    # quindi uno stato/allarme separato — puo' cadere anche quando l'altro
    # e' su, e viceversa
    nas_backup_ok = controlla_nas(NAS_BACKUP_PATH)
    _transizione(
        stato, "nas_backup",
        nas_backup_ok,
        lambda: avvisa(costruisci_messaggio_critical(
            "NAS backup non raggiungibile",
            f"{NAS_BACKUP_PATH} non e' montato o non risponde")),
        lambda: avvisa(costruisci_messaggio_recovery("NAS backup")),
    )

    # ---- export configurazione: eta' dell'ultimo export riuscito sul NAS.
    # None (non verificabile, NAS giu') non va a _transizione: lo stato
    # precedente resta esattamente com'era, ne' un falso OK ne' un
    # secondo alert sopra a quello gia' dedicato al NAS.
    export_ok, export_dettaglio = controlla_export_config(nas_backup_ok, adesso=adesso)
    if export_ok is not None:
        _transizione(
            stato, "export_config",
            export_ok,
            lambda: avvisa(costruisci_messaggio_critical(
                "Export configurazione non aggiornato", export_dettaglio)),
            lambda: avvisa(costruisci_messaggio_recovery("Export configurazione")),
        )

    # ---- disco
    livello_disco, liberi_pct = controlla_disco()
    disco_ok = livello_disco not in ("critical", "warning")
    _transizione(
        stato, "disco",
        disco_ok,
        lambda: avvisa(
            costruisci_messaggio_critical("Spazio disco critico",
                                           f"{liberi_pct:.0f}% liberi")
            if livello_disco == "critical" else
            costruisci_messaggio_warning("Spazio disco basso",
                                          f"{liberi_pct:.0f}% liberi")),
        lambda: avvisa(costruisci_messaggio_recovery("Spazio disco")),
    )

    # ---- RAM: solo se alta per piu' controlli consecutivi
    ram_pct = controlla_ram()
    consecutivi = stato.get("ram_consecutivi", 0)
    if ram_pct >= RAM_WARNING:
        consecutivi += 1
    else:
        consecutivi = 0
    stato["ram_consecutivi"] = consecutivi
    ram_ok = consecutivi < RAM_CONSECUTIVI
    _transizione(
        stato, "ram",
        ram_ok,
        lambda: avvisa(costruisci_messaggio_warning(
            "RAM molto alta", f"{ram_pct:.0f}% usata per {RAM_CONSECUTIVI} controlli di fila")),
        lambda: avvisa(costruisci_messaggio_recovery("RAM")),
    )

    # ---- 5xx: crescita anomala
    quanti_5xx = conta_5xx_recenti()
    errori_5xx_ok = quanti_5xx < SOGLIA_5XX
    _transizione(
        stato, "5xx",
        errori_5xx_ok,
        lambda: avvisa(costruisci_messaggio_warning(
            "Errori 5xx in crescita", f"{quanti_5xx} errori negli ultimi {FINESTRA_5XX_MIN} minuti")),
        lambda: avvisa(costruisci_messaggio_recovery("Pagine in errore")),
    )

    # Snapshot dei valori grezzi dell'ultimo giro, cosi' un consumatore
    # esterno (es. il comando /health del bot) puo' mostrarli senza dover
    # rieseguire i controlli: sola lettura, non cambia ne' le soglie ne'
    # la logica di anti-spam sopra, che restano quella di sempre.
    stato["ultimo_check"] = adesso.isoformat(timespec="seconds")
    stato["dettagli_ultimo"] = {
        "sito_ok": sito_ok, "sito_dettaglio": sito_dettaglio,
        "backend_ok": backend_ok, "backend_dettaglio": backend_dettaglio,
        "nginx_ok": nginx_ok, "nginx_dettaglio": nginx_dettaglio,
        "app_ok": stato.get("photocarcifo.service", {}).get("ok"),
        "bot_ok": stato.get("photocarcifo-bot.service", {}).get("ok"),
        "db_ok": db_ok, "db_dettaglio": db_dettaglio,
        "db_integrity_quando": stato.get("db_integrity_check_quando"),
        "db_integrity_ok": stato.get("db_integrity", {}).get("ok"),
        "backup_db_ok": backup_ok, "backup_db_dettaglio": backup_dettaglio,
        "backup_db_integrity_quando": stato.get("backup_db_integrity_quando"),
        "backup_db_integrity_ok": stato.get("backup_db_integrity", {}).get("ok"),
        "nas_backup_ok": nas_backup_ok,
        "export_config_ok": export_ok, "export_config_dettaglio": export_dettaglio,
        "disco_livello": livello_disco, "disco_liberi_pct": liberi_pct,
        "ram_pct": ram_pct, "ram_ok": ram_ok,
        "quanti_5xx": quanti_5xx, "5xx_ok": errori_5xx_ok,
    }

    scrivi_stato(stato)
    return stato


def main():
    try:
        esegui_controlli()
    except Exception as errore:
        # Un bug nel monitor non deve restare silenzioso: lo si scrive nel
        # log (visibile anche da systemd/journalctl) e si esce con errore,
        # cosi' `systemctl status` mostra il fallimento invece di un
        # innocuo "successo" che nasconde il problema.
        loga(f"ERRORE monitor: {errore!r}")
        print(f"Errore nel monitor: {errore}", file=sys.stderr)
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
