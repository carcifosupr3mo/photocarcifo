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
