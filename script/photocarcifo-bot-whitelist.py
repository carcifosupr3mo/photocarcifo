#!/usr/bin/env python3
"""Toglie dai ban di fail2ban i crawler veri dei motori di ricerca.

Nato da un problema preciso: photocarcifo-scansioni banna chi colleziona
troppi "pagina non trovata" in poco tempo (vedi il filtro per la storia
completa). Un crawler vero non chiede mai file come /rclone.conf o
/.env, quindi in pratica non ci finisce dentro — ma un link vecchio o
una pagina tolta puo' fargli comunque incontrare una serie di 404, ed e'
un rischio che vale la pena eliminare del tutto: un ban a Googlebot vale
giorni di indicizzazione persa, molto piu' caro di un migliaio di
scansioni lasciate perdere per errore.

Il punto delicato e' che l'indirizzo IP da solo non prova niente:
chiunque puo' scrivere "Googlebot" nello User-Agent, e Google/Microsoft/
Apple ospitano anche macchine virtuali qualsiasi sugli stessi intervalli
usati dai crawler (e' successo il 29/08/2026: tre degli otto indirizzi
bannati da photocarcifo-scansioni risultavano su intervalli Google Cloud
o Microsoft Azure, ma cercavano /rclone.conf e simili — non erano
Googlebot ne' Bingbot, solo scanner ospitati li' sopra). L'unica verifica
che regge e' quella che i motori stessi documentano: PTR+A. Si chiede il
nome host all'indirizzo (reverse DNS), si controlla che finisca nel
dominio ufficiale del motore, poi si richiede la risoluzione DIRETTA di
quel nome e si controlla che torni allo stesso indirizzo di partenza. Un
solo passo (solo il reverse) si falsifica con un PTR scritto a piacere su
un server qualsiasi; il doppio controllo no, perche' richiederebbe
controllare anche la zona DNS diretta del motore — la stessa identica
logica gia' in uso in photocarcifo-ban-alert.py (e_bingbot_verificato),
qui estesa a tutti i motori rilevanti e usata per agire, non solo per
segnalare.

Cosa fa, ad ogni esecuzione:
  1. legge gli indirizzi attualmente bannati in TUTTE le jail di fail2ban
     (non solo photocarcifo-scansioni: un crawler puo' incappare anche
     in nginx-botsearch o nginx-limit-req su un sito con tante pagine);
  2. per ognuno, verifica se e' un crawler vero con PTR+A;
  3. se lo e': lo sblocca (fail2ban-client set <jail> unbanip) e lo
     aggiunge alla whitelist permanente, cosi' fail2ban non lo ribanna
     mai piu' e non serve rifare il lookup ad ogni giro;
  4. l'indirizzo verificato va ad aggiungersi a ignoreip dentro
     /etc/fail2ban/jail.d/photocarcifo.local — NON in un file a parte:
     fail2ban fonde piu' file jail.d/*.local con un ConfigParser
     normale, e una seconda sezione [DEFAULT] in un file diverso
     SOVRASCRIVE ignoreip invece di sommarsi (verificato: l'ultimo file
     letto in ordine alfabetico vince). L'unico modo che funziona
     davvero e' modificare la riga ignoreip che gia' esiste, aggiungendo
     in coda solo gli indirizzi nuovi e lasciando intatti quelli scelti
     a mano (se stessi, rete di casa) e il commento che li spiega;
  5. la modifica viene poi ricaricata con un fail2ban-client reload,
     mai un restart: un restart perderebbe lo stato di tutti i ban in
     corso sulle altre jail per un motivo che non le riguarda.

Chi banna resta fail2ban, come per photocarcifo-ban-alert.py: qui non
c'e' nessuna logica su QUANDO bannare, solo su quali ban disfare perche'
il bannato era in realta' un motore di ricerca.

Uso:
    photocarcifo-bot-whitelist.py            sblocca e aggiorna la whitelist
    photocarcifo-bot-whitelist.py --prova    mostra cosa farebbe, non tocca nulla

Pensato per girare da cron ogni pochi minuti (vedi il file crontab
installato insieme a questo script).
"""
import re
import socket
import subprocess
import sys
from pathlib import Path

LOG = "/var/lib/photocarcifo/bot-whitelist.log"
LOG_MASSIMO = 500_000

# La riga ignoreip da modificare vive qui, non in un file a parte: vedi
# la spiegazione in cima al file sul perche' un secondo [DEFAULT] in un
# altro file non funzionerebbe (sovrascrive invece di sommarsi).
JAIL_LOCAL = "/etc/fail2ban/jail.d/photocarcifo.local"

# Riga di commento che apre il blocco di indirizzi aggiunti da questo
# script, come continuazione indentata della riga ignoreip: fail2ban usa
# ConfigParser, che scarta le righe di commento anche dentro un valore
# multi-riga (verificato), quindi il marcatore resta leggibile nel file
# senza finire nella lista di indirizzi che fail2ban legge davvero. Tutto
# quello che sta DOPO questa riga e prima della fine del blocco ignoreip
# viene considerato "gestito da questo script" e riscritto ad ogni giro;
# tutto quello che sta PRIMA (gli indirizzi scelti a mano) resta intatto.
MARCATORE = "# --- crawler verificati (photocarcifo-bot-whitelist.py, non modificare a mano) ---"

TIMEOUT_DNS = 4  # secondi: un lookup lento non deve mai bloccare il giro di cron

# Un motore per riga: suffisso del reverse DNS che deve avere l'indirizzo,
# come lo stesso motore lo documenta pubblicamente. Il forward lookup del
# nome trovato deve poi tornare allo stesso IP di partenza (vedi sopra).
#   Google:      https://developers.google.com/search/docs/crawling-indexing/verifying-googlebot
#   Bing:        https://www.bing.com/webmasters/help/how-to-verify-bingbot-3905dc26
#   Apple:       https://support.apple.com/en-us/119829 (Applebot)
#   DuckDuckGo:  pubblica solo intervalli IP fissi, non PTR — verificato a parte sotto
SUFFISSI_MOTORI = {
    "googlebot": (".googlebot.com.", ".google.com."),
    "bingbot": (".search.msn.com.",),
    "applebot": (".applebot.apple.com.",),
}

# DuckDuckGo non pubblica un dominio PTR da verificare: pubblica un
# elenco fisso di indirizzi (https://duckduckgo.com/duckduckgo-help-pages/results/duckduckbot/).
# Range ridotto e stabile, aggiornato di rado: si tiene qui invece di
# fare polling di quella pagina ad ogni esecuzione.
RETI_DUCKDUCKGO = ("20.191.45.212/32", "40.88.21.235/32")


def loga(riga):
    p = Path(LOG)
    try:
        if p.exists() and p.stat().st_size > LOG_MASSIMO:
            p.write_text(p.read_text(errors="replace")[-LOG_MASSIMO // 2:])
        with p.open("a") as f:
            from datetime import datetime, timezone
            ora = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
            f.write(f"{ora} {riga}\n")
    except Exception:
        pass  # un log che non si scrive non deve mai far fallire il giro


def verifica_ptr_a(ip, suffissi):
    """PTR+A generico: vedi la spiegazione in cima al file. True solo se
    entrambi i passi tornano coerenti, False in ogni altro caso — incluso
    qualunque errore di rete o di risoluzione, per cui un DNS lento o
    irraggiungibile lascia semplicemente l'indirizzo bannato com'era."""
    try:
        socket.setdefaulttimeout(TIMEOUT_DNS)
        nome, _, _ = socket.gethostbyaddr(ip)
    except Exception:
        return False
    # gethostbyaddr normalmente non include il punto finale del FQDN
    # (dipende dal resolver di sistema): lo si aggiunge qui, cosi' i
    # suffissi si scrivono in forma canonica senza doverli duplicare.
    if not nome.endswith("."):
        nome += "."
    if not any(nome.endswith(s) for s in suffissi):
        return False
    try:
        risolto = socket.gethostbyname(nome)
    except Exception:
        return False
    return risolto == ip


def motore_di(ip):
    """Nome del motore verificato per questo indirizzo, o None. Prova
    prima i motori con PTR+A, poi gli intervalli fissi di DuckDuckGo."""
    for motore, suffissi in SUFFISSI_MOTORI.items():
        if verifica_ptr_a(ip, suffissi):
            return motore
    import ipaddress
    try:
        indirizzo = ipaddress.ip_address(ip)
    except ValueError:
        return None
    for rete in RETI_DUCKDUCKGO:
        if indirizzo in ipaddress.ip_network(rete):
            return "duckduckbot"
    return None


def jail_attive():
    """Elenco delle jail configurate, letto da fail2ban stesso (non dal
    file di configurazione): se una jail e' disabilitata o non ancora
    caricata non deve comparire, altrimenti unbanip fallirebbe su di
    lei ad ogni giro."""
    try:
        out = subprocess.run(
            ["fail2ban-client", "status"], capture_output=True, text=True,
            timeout=10, check=True).stdout
    except Exception as errore:
        loga(f"ERRORE lettura elenco jail: {errore}")
        return []
    m = re.search(r"Jail list:\s*(.+)", out)
    if not m:
        return []
    return [j.strip() for j in m.group(1).split(",") if j.strip()]


def bannati_in(jail):
    try:
        out = subprocess.run(
            ["fail2ban-client", "status", jail], capture_output=True, text=True,
            timeout=10, check=True).stdout
    except Exception as errore:
        loga(f"ERRORE lettura ban di {jail}: {errore}")
        return []
    m = re.search(r"Banned IP list:\s*(.*)", out)
    if not m:
        return []
    return [ip.strip() for ip in m.group(1).split() if ip.strip()]


def leggi_crawler_whitelistati():
    """Indirizzi gia' aggiunti da questo script in un giro precedente,
    letti dal blocco dopo MARCATORE dentro jail.local. Un errore qui
    (file assente, marcatore assente) restituisce lista vuota: il primo
    giro utile lo crea da zero, vedi scrivi_jail_local."""
    p = Path(JAIL_LOCAL)
    if not p.exists():
        return []
    testo = p.read_text()
    if MARCATORE not in testo:
        return []
    dopo = testo.split(MARCATORE, 1)[1]
    # Il blocco continua finche' le righe restano indentate (continuazione
    # del valore ignoreip per ConfigParser); la prima riga non indentata
    # (comprese le righe vuote) chiude il blocco.
    reti = []
    for riga in dopo.splitlines()[1:]:
        if not riga.strip():
            break
        if not riga[:1].isspace():
            break
        reti.extend(riga.split())
    return reti


def scrivi_jail_local(nuovi_indirizzi):
    """Aggiunge nuovi_indirizzi al blocco dopo MARCATORE dentro la riga
    ignoreip di jail.local, senza toccare nient'altro nel file — ne' gli
    indirizzi scelti a mano, ne' le altre jail, ne' i commenti. Se il
    marcatore non esiste ancora lo crea in coda al blocco ignoreip
    esistente (subito prima della prima riga vuota o non indentata dopo
    'ignoreip =')."""
    p = Path(JAIL_LOCAL)
    testo = p.read_text()
    esistenti = leggi_crawler_whitelistati()
    unione = sorted(set(esistenti) | set(nuovi_indirizzi))
    blocco_nuovo = "\n".join(f"           {ip}" for ip in unione)

    if MARCATORE in testo:
        prima, dopo = testo.split(MARCATORE, 1)
        righe_dopo = dopo.splitlines(keepends=True)
        i = 1  # riga 0 e' il resto della riga del marcatore (newline)
        while i < len(righe_dopo) and righe_dopo[i].strip() and righe_dopo[i][:1].isspace():
            i += 1
        resto = "".join(righe_dopo[i:])
        testo_nuovo = f"{prima}{MARCATORE}\n{blocco_nuovo}\n{resto}"
    else:
        # Prima volta: si aggancia in coda al primo blocco ignoreip trovato.
        righe = testo.splitlines(keepends=True)
        for idx, riga in enumerate(righe):
            if riga.strip().startswith("ignoreip"):
                fine = idx + 1
                while fine < len(righe) and righe[fine].strip() and righe[fine][:1].isspace():
                    fine += 1
                righe[fine:fine] = [f"           {MARCATORE}\n", f"{blocco_nuovo}\n"]
                testo_nuovo = "".join(righe)
                break
        else:
            loga("ERRORE: nessuna riga ignoreip trovata in jail.local, whitelist non scritta")
            return False

    # Scrittura atomica: mai un jail.local a meta' se il processo muore
    # a meta' write, fail2ban lo rileggerebbe rotto al prossimo reload.
    tmp = p.with_suffix(".local.tmp")
    tmp.write_text(testo_nuovo)
    tmp.replace(p)
    return True


def config_valida():
    """fail2ban-client -t verifica la sintassi senza applicarla: se
    scrivi_jail_local ha prodotto un file rotto, meglio scoprirlo qui che
    con un reload che lascia fail2ban a meta' configurato."""
    try:
        r = subprocess.run(["fail2ban-client", "-t"], capture_output=True,
                            text=True, timeout=15)
        return r.returncode == 0
    except Exception as errore:
        loga(f"ERRORE verifica config: {errore}")
        return False


def ricarica_fail2ban():
    """Reload, mai restart: un restart perde lo stato di tutti i ban in
    corso su ogni jail per un motivo (un crawler su UNA jail) che non le
    riguarda affatto."""
    try:
        subprocess.run(["fail2ban-client", "reload"], capture_output=True,
                        text=True, timeout=20, check=True)
        return True
    except Exception as errore:
        loga(f"ERRORE reload fail2ban: {errore}")
        return False


def main():
    prova = "--prova" in sys.argv[1:]

    whitelist_attuale = leggi_crawler_whitelistati()
    da_sbloccare = []  # [(jail, ip, motore), ...]

    for jail in jail_attive():
        for ip in bannati_in(jail):
            motore = motore_di(ip)
            if motore:
                da_sbloccare.append((jail, ip, motore))

    if not da_sbloccare:
        if prova:
            print("Nessun crawler verificato fra gli indirizzi attualmente bannati.")
        return

    for jail, ip, motore in da_sbloccare:
        messaggio = f"{ip} verificato come {motore} (PTR+A), bannato in {jail}"
        if prova:
            print(f"[prova] sbloccherei {messaggio}")
            continue
        try:
            subprocess.run(["fail2ban-client", "set", jail, "unbanip", ip],
                            capture_output=True, text=True, timeout=10, check=True)
            loga(f"SBLOCCATO {messaggio}")
        except Exception as errore:
            loga(f"ERRORE sblocco {ip} in {jail}: {errore}")

    if prova:
        return

    nuovi = sorted({ip for _, ip, _ in da_sbloccare} - set(whitelist_attuale))
    if not nuovi:
        return  # gia' tutti in whitelist da un giro precedente, sblocco sopra gia' bastava

    prima = Path(JAIL_LOCAL).read_text()
    if not scrivi_jail_local(nuovi):
        return
    if not config_valida():
        loga("ERRORE: jail.local non valido dopo la scrittura, ripristino la versione precedente")
        Path(JAIL_LOCAL).write_text(prima)
        return
    if ricarica_fail2ban():
        loga(f"whitelist aggiornata con {len(nuovi)} indirizzo/i nuovo/i: {', '.join(nuovi)}")
    else:
        loga("whitelist scritta ma reload fail2ban fallito: verificare a mano")


if __name__ == "__main__":
    main()
