#!/usr/bin/env python3
"""Decide se un ban di photocarcifo-scansioni diventa un blocco vero.

Nato il 31/08/2026 su richiesta esplicita: gli indirizzi ospitati su un
datacenter/hosting pubblico (Google Cloud, Microsoft Azure, AWS, OVH,
Hetzner...) non devono mai essere bloccati per davvero, nemmeno quando
il path richiesto e' quello di un vero tentativo di intrusione (.env,
RCE, credenziali — vedi filter.d/photocarcifo-scansioni.conf). Solo
l'avviso Telegram, mai il blocco.

Attenzione, e' stato segnalato esplicitamente prima di scrivere questo
script: "datacenter/hosting" NON equivale a "motore di ricerca". La
stragrande maggioranza degli attacchi automatizzati visti su questo
sito (RCE, furto di credenziali AWS, webshell — vedi
/var/lib/photocarcifo/ban-storico.json) sono partiti proprio da VM
affittate su questi stessi cloud, non da Googlebot o Bingbot. Con
questo script quegli attacchi smettono di essere bloccati: restano
solo segnalati. La protezione mirata per i crawler VERI dei motori di
ricerca (verifica reverse+forward DNS, non il tipo di rete) resta
quella di photocarcifo-bot-whitelist.py, indipendente da questo script
e non modificata.

Perche' non si puo' fare con un semplice banaction in jail.local: fail2ban
decide "banna" o "non banna" senza nessun modo nativo di guardare prima
il tipo di rete dell'indirizzo — quel controllo richiede una richiesta
di rete (ip-api.com), e fail2ban non supporta un'azione "condizionale".
Per questo la jail photocarcifo-scansioni NON usa piu' iptables-multiport
come actionban/actionunban: usa questo script, che decide lui se
scrivere davvero la regola iptables nella catena che fail2ban ha gia'
creato (f2b-photocarcifo-scansioni — quella la crea sempre
iptables-multiport via actionstart, invariato).

Non si puo' nemmeno chiamare "fail2ban-client set <jail> banip" da
dentro questo script per bannare per davvero: quel comando fa ripartire
TUTTE le azioni della jail, incluso questo stesso script — loop
infinito garantito. Si scrive la regola iptables direttamente, con lo
stesso comando che userebbe iptables-multiport.

fail2ban traccia comunque OGNI indirizzo come "bannato" nel suo stato
interno indipendentemente da questo script (e' cosi' che funziona
sempre, vedi il commento in photocarcifo-bot-whitelist.py): "Currently
banned" in fail2ban-client status include quindi anche gli indirizzi
su datacenter, anche se per loro non esiste nessuna regola iptables
reale — e' innocuo, serve solo a far scadere il bantime senza dover
riscrivere anche quella logica.

Uso (chiamato da fail2ban, vedi action.d/photocarcifo-scansioni-decidi.conf):
    photocarcifo-scansioni-decidi.py ban <jail> <ip> <tentativi> <righe-base64>
    photocarcifo-scansioni-decidi.py unban <jail> <ip>
"""
import importlib.util
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
LOG = "/var/lib/photocarcifo/scansioni-decidi.log"
LOG_MASSIMO = 500_000

# Le stesse regole/comandi che iptables-multiport userebbe (vedi
# /etc/fail2ban/action.d/iptables.conf): stessa catena, stesso tipo di
# blocco, stessa opzione di locking (-w, per non litigare con le altre
# jail che scrivono regole iptables in parallelo), solo eseguiti da qui
# invece che in automatico su ogni match.
IPTABLES = ["iptables", "-w"]
BLOCKTYPE = "REJECT --reject-with icmp-port-unreachable"


def loga(riga):
    p = Path(LOG)
    try:
        if p.exists() and p.stat().st_size > LOG_MASSIMO:
            p.write_text(p.read_text(errors="replace")[-LOG_MASSIMO // 2:])
        with p.open("a") as f:
            ora = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
            f.write(f"{ora} {riga}\n")
    except Exception:
        pass  # un log che non si scrive non deve mai bloccare la decisione


def _carica_alert():
    """Il modulo ban-alert.py (nome con trattini, non importabile con
    'import' normale) si carica cosi' per riusare geolocalizza(), la
    sua cache e l'accodamento Telegram gia' scritti li' — nessuna
    logica di rete o di notifica duplicata in questo file."""
    spec = importlib.util.spec_from_file_location(
        "photocarcifo_ban_alert", SCRIPT_DIR / "photocarcifo-ban-alert.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def e_hosting(ip, alert):
    """True se ip-api.com classifica l'indirizzo come datacenter/hosting.
    Un lookup fallito (servizio irraggiungibile, timeout) ritorna False:
    nel dubbio si banna, non si lascia passare — coerente con com'era il
    comportamento PRIMA che esistesse questa eccezione."""
    geo = alert.geolocalizza(ip)
    return bool(geo and geo.get("rete") == "Datacenter/hosting")


def chain_esiste(jail):
    # iptables -S sulla catena fallisce (returncode != 0) se la catena
    # non esiste: e' il modo standard di verificarlo senza doverla
    # creare o interpretare l'output.
    r = subprocess.run(IPTABLES + ["-S", f"f2b-{jail}"], capture_output=True, timeout=5)
    return r.returncode == 0


def regola_esiste(jail, ip):
    r = subprocess.run(
        IPTABLES + ["-C", f"f2b-{jail}", "-s", ip, "-j"] + BLOCKTYPE.split(),
        capture_output=True, timeout=5)
    return r.returncode == 0


def banna_per_davvero(jail, ip):
    if not chain_esiste(jail):
        loga(f"ERRORE ban {ip} in {jail}: la catena f2b-{jail} non esiste "
            f"(la jail e' partita correttamente?)")
        return False
    if regola_esiste(jail, ip):
        return True  # gia' bannato (es. doppio evento nella stessa finestra), niente da fare
    r = subprocess.run(
        IPTABLES + ["-I", f"f2b-{jail}", "1", "-s", ip, "-j"] + BLOCKTYPE.split(),
        capture_output=True, text=True, timeout=5)
    if r.returncode != 0:
        loga(f"ERRORE ban {ip} in {jail}: {r.stderr.strip()}")
        return False
    return True


def sblocca_per_davvero(jail, ip):
    if not regola_esiste(jail, ip):
        return True  # non era mai stato bannato per davvero (era hosting): niente da togliere
    r = subprocess.run(
        IPTABLES + ["-D", f"f2b-{jail}", "-s", ip, "-j"] + BLOCKTYPE.split(),
        capture_output=True, text=True, timeout=5)
    if r.returncode != 0:
        loga(f"ERRORE unban {ip} in {jail}: {r.stderr.strip()}")
        return False
    return True


def comando_ban(jail, ip, tentativi, righe_b64):
    alert = _carica_alert()
    import base64
    righe = []
    if righe_b64:
        try:
            righe = base64.b64decode(righe_b64).decode("utf-8", "replace").splitlines()
        except Exception:
            righe = []

    hosting = e_hosting(ip, alert)
    if hosting:
        loga(f"SOLO AVVISO {ip} in {jail}: datacenter/hosting, nessun blocco reale")
    else:
        ok = banna_per_davvero(jail, ip)
        loga(f"BLOCCATO {ip} in {jail}: {'ok' if ok else 'ERRORE, vedi sopra'}")

    # La notifica passa comunque da elabora() (stesso messaggio, stesso
    # accodamento/raggruppamento gia' in uso): solo_avviso=hosting dice
    # esplicitamente al messaggio se questo evento e' sfociato in un
    # blocco reale o no, senza dover inventare pseudo-nomi di jail.
    alert.elabora(jail, ip, tentativi, righe, solo_avviso=hosting)


def comando_unban(jail, ip):
    ok = sblocca_per_davvero(jail, ip)
    loga(f"UNBAN {ip} in {jail}: {'ok' if ok else 'ERRORE, vedi sopra'}")


def main():
    if len(sys.argv) < 2:
        sys.exit(0)
    azione = sys.argv[1]
    try:
        if azione == "ban" and len(sys.argv) >= 5:
            jail, ip, tentativi = sys.argv[2], sys.argv[3], sys.argv[4]
            righe_b64 = sys.argv[5] if len(sys.argv) > 5 else ""
            comando_ban(jail, ip, tentativi, righe_b64)
        elif azione == "unban" and len(sys.argv) >= 4:
            jail, ip = sys.argv[2], sys.argv[3]
            comando_unban(jail, ip)
    except Exception as errore:
        loga(f"ERRORE non gestito ({azione}): {errore!r}")
    sys.exit(0)  # sempre 0: un guasto qui non deve mai riflettersi su fail2ban


if __name__ == "__main__":
    main()
