#!/usr/bin/env python3
"""Notifica su Telegram quando fail2ban banna davvero un indirizzo.

Tutto su Telegram: nessun canale WhatsApp (mai configurato, si e'
scelto di tenere un solo canale invece di mantenere un percorso
alternativo mai usato). Il livello CRITICAL/WARNING resta nel testo del
messaggio stesso — distingue la gravita' a colpo d'occhio, ma non
sceglie piu' un canale diverso.

Chi banna e' fail2ban, non questo script: qui non c'e' nessuna logica di
"quando bannare", solo "cosa fare quando e' appena successo". Il punto in
cui un indirizzo passa da sospetto a bannato e' l'azione "actionban" delle
jail configurate in /etc/fail2ban/jail.d/photocarcifo.local — fail2ban
stesso chiama QUESTO script, una volta per ban, passando l'indirizzo, la
jail, quante volte ha sbagliato e le righe di registro che l'hanno fatto
scattare (vedi action.d/photocarcifo-alert.conf). Nessun polling: la
notifica parte nello stesso istante del ban, perche' fail2ban la fa
scattare lui.

Ordine delle operazioni (fondamentale): il ban e' GIA' avvenuto quando
questo script viene chiamato (fail2ban esegue prima actionban, poi le
azioni di notifica in parallelo) — un errore qui dentro, o un servizio
esterno lento/offline, non annulla mai il ban e non lo ritarda: nel peggiore
dei casi arriva un avviso in meno, mai una porta che resta aperta.

I messaggi non partono piu' uno per ogni ban: si accodano in un file
(CODA_TELEGRAM) e vengono inviati insieme, raggruppati, alla prima
occasione utile entro FINESTRA_RAGGRUPPAMENTO secondi dal primo della
raffica (vedi accoda_o_invia()). Nato il 29/08/2026: con maxretry=1 su
photocarcifo-scansioni un solo attacco con molti path diversi genera un
ban al secondo, quindi altrettanti messaggi separati — nessuna
informazione persa nel raggrupparli, e' comunque lo stesso quadro "sotto
attacco da questi indirizzi", solo un messaggio invece di dieci.

Uso:
    photocarcifo-ban-alert.py <jail> <ip> <tentativi> <righe-di-registro-base64>

Le righe di registro arrivano codificate in base64 perche' possono
contenere caratteri che romperebbero il passaggio come argomento di shell
(virgolette, percent-encoding, eccetera) — fail2ban le passa gia' come
testo libero via <matches>, e un unico livello di codifica qui evita
qualunque interpretazione ambigua sulla riga di comando.
"""
import base64
import fcntl
import ipaddress
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

CONFIG = "/etc/photocarcifo-telegram.conf"
CACHE_GEO = "/var/lib/photocarcifo/ban-geo-cache.json"
LOG = "/var/lib/photocarcifo/ban-alert.log"
CACHE_TTL = 6 * 3600     # un IP non cambia paese/ISP nel giro di poche ore
TIMEOUT_LOOKUP = 4       # secondi: un lookup lento non deve mai bloccare
LOG_MASSIMO = 2_000_000

# Snapshot di ogni ban: quello che /bloccati legge, cosi' non rifa' mai i
# lookup GeoIP/AbuseIPDB per mostrare la lista — li ha gia' fatti una volta
# sola, qui, nell'istante del ban. Tenuto separato dalla cache dei lookup
# (CACHE_GEO ha un TTL e scade, questo file invece e' lo storico dei ban
# stessi e resta finche' non viene ripulito).
STORICO = "/var/lib/photocarcifo/ban-storico.json"
STORICO_MASSIMO = 500  # ban piu' vecchi di questi si scartano, non deve crescere per sempre

# Coda dei messaggi in attesa di essere raggruppati in un solo invio
# Telegram. Nata il 29/08/2026: con maxretry=1 su photocarcifo-scansioni
# un attacco con molti path diversi genera un ban al secondo, e altrettanti
# messaggi Telegram separati — inutile e fastidioso quando arrivano
# ravvicinati, l'informazione e' la stessa "sto sotto attacco da questi
# indirizzi", non serve un telefono che vibra ad ogni singolo IP.
CODA_TELEGRAM = "/var/lib/photocarcifo/telegram-coda.jsonl"
CODA_LOCK = "/var/lib/photocarcifo/telegram-coda.lock"
FINESTRA_RAGGRUPPAMENTO = 60  # secondi: vedi accoda_o_invia() per il meccanismo

# --------------------------------------------------------------- config

def leggi_config(percorso=CONFIG):
    """Stesso formato/parsing di app/telegram_avvisi.py e dello script
    del bot: un solo posto per la sintassi del file, riusato ovunque
    invece di riscritto da capo."""
    valori = {}
    try:
        with open(percorso, encoding="utf-8") as f:
            for riga in f:
                riga = riga.strip()
                if riga.startswith("#") or "=" not in riga:
                    continue
                k, _, v = riga.partition("=")
                valori[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return valori


def leggi_env(config, chiave):
    """Le variabili WhatsApp/AbuseIPDB, se presenti, stanno nello stesso
    file di configurazione del bot (un solo posto per i secret di questo
    server, non sparsi fra .env diversi) — mai un default che sembri una
    chiave vera, solo stringa vuota se assente."""
    return config.get(chiave, "").strip()


def loga(riga):
    try:
        p = Path(LOG)
        if p.exists() and p.stat().st_size > LOG_MASSIMO:
            p.unlink()
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')} {riga}\n")
    except Exception:
        pass


# ------------------------------------------------------ motivo del ban

# Nome della jail -> (etichetta leggibile, livello). Il livello decide
# quale canale riceve l'allerta (vedi FASE 10 della richiesta): non tutti
# i ban meritano di interrompere qualcuno con un messaggio prioritario.
JAIL_INFO = {
    "photocarcifo-scansioni": ("Scansione di file/percorsi sensibili", "CRITICAL"),
    "photocarcifo-scansioni-attivita": ("Volume di scansione su path generici (nessun ban)", "WARNING"),
    "photocarcifo-login": ("Tentativi di password ripetuti (brute force)", "CRITICAL"),
    "pannello-login": ("Password/2FA ripetuti sul pannello Proxmox", "CRITICAL"),
    "nginx-botsearch": ("Scansione WordPress/CMS", "WARNING"),
    "nginx-limit-req": ("Troppe richieste al secondo (rate limit)", "WARNING"),
    "sshd": ("Tentativi di accesso SSH", "CRITICAL"),
}

# Jail che non bannano mai per davvero (vedi jail.d/photocarcifo.local:
# nessun banaction reale in azione, solo questo script) — il messaggio
# deve dirlo chiaramente, non far credere che l'indirizzo sia stato
# bloccato quando invece puo' continuare a chiedere pagine come prima.
JAIL_SOLO_AVVISO = {"photocarcifo-scansioni-attivita"}


def motivo_e_livello(jail):
    return JAIL_INFO.get(jail, (f"Comportamento automatizzato rilevato ({jail})", "WARNING"))


# Per affinare il motivo quando possibile: se le righe intercettate
# mostrano chiaramente un path noto (.env, wp-admin...) lo si nomina,
# invece di restare sul solo nome della jail.
_PATH_NOTI = (
    (re.compile(r"\.env\b"), "tentativi su /.env"),
    (re.compile(r"wp-admin|wp-login|wp-json"), "scansione WordPress"),
    (re.compile(r"phpmyadmin", re.I), "scansione phpMyAdmin"),
    (re.compile(r"\.\.[/%]"), "path traversal"),
    (re.compile(r"cgi-bin"), "sfruttamento CGI"),
    (re.compile(r"graphql"), "scansione endpoint GraphQL"),
    (re.compile(r"\.git/"), "esposizione repository .git"),
)


def affina_motivo(motivo_base, righe):
    testo = "\n".join(righe)
    trovati = [etichetta for pattern, etichetta in _PATH_NOTI if pattern.search(testo)]
    if not trovati:
        return motivo_base
    return motivo_base + " — " + ", ".join(trovati[:2])


# --------------------------------------------------- righe di registro

def estrai_dettagli(righe):
    """Dalle righe grezze di nginx/log: i path piu' frequenti (max 5,
    come richiesto), l'ultimo status code e user-agent visti. Un log
    nginx e' 'IP - - [data] "METODO /path HTTP/1.1" STATUS SIZE "referer"
    "user-agent"': non serve un parser completo, bastano due espressioni
    regolari mirate a quello che davvero serve mostrare."""
    path_pattern = re.compile(
        r'"(?:GET|POST|HEAD|PUT|DELETE|OPTIONS|PATCH|PROPFIND) (\S+) HTTP')
    status_pattern = re.compile(r'HTTP/[^"]*"\s+(\d{3})')
    ua_pattern = re.compile(r'"[^"]*"\s*$')

    conteggio = {}
    ultimo_status = None
    ultimo_ua = None
    for riga in righe:
        m = path_pattern.search(riga)
        if m:
            p = m.group(1)[:120]  # un path assurdamente lungo non deve rompere il messaggio
            conteggio[p] = conteggio.get(p, 0) + 1
        s = status_pattern.search(riga)
        if s:
            ultimo_status = s.group(1)
        u = ua_pattern.search(riga)
        if u:
            ultimo_ua = u.group(0).strip('"')[:100]

    principali = sorted(conteggio, key=conteggio.get, reverse=True)[:5]
    return principali, ultimo_status, ultimo_ua


# --------------------------------------------------------------- cache

def _leggi_cache():
    try:
        with open(CACHE_GEO, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _scrivi_cache(dati):
    try:
        Path(CACHE_GEO).parent.mkdir(parents=True, exist_ok=True)
        with open(CACHE_GEO, "w", encoding="utf-8") as f:
            json.dump(dati, f)
    except Exception:
        pass


def _dalla_cache(ip):
    cache = _leggi_cache()
    voce = cache.get(ip)
    if not voce:
        return None
    if time.time() - voce.get("_quando", 0) > CACHE_TTL:
        return None
    return voce


def _in_cache(ip, dati):
    cache = _leggi_cache()
    dati = dict(dati)
    dati["_quando"] = time.time()
    cache[ip] = dati
    # Non deve crescere per sempre: si tiene solo un migliaio di IP,
    # scartando le voci piu' vecchie — non serve un vero LRU per questo
    # volume, una cache che si autolimita in modo semplice basta.
    if len(cache) > 1000:
        piu_vecchi = sorted(cache, key=lambda k: cache[k].get("_quando", 0))
        for vecchio in piu_vecchi[:len(cache) - 1000]:
            cache.pop(vecchio, None)
    _scrivi_cache(cache)


# ------------------------------------------------------------- storico

def _leggi_storico():
    try:
        with open(STORICO, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _scrivi_storico(dati):
    try:
        Path(STORICO).parent.mkdir(parents=True, exist_ok=True)
        with open(STORICO, "w", encoding="utf-8") as f:
            json.dump(dati, f)
    except Exception:
        pass


def salva_snapshot(jail, ip, tentativi, motivo, principali, status, ua, geo, abuse):
    """Un ban, i dati che lo spiegano: esattamente quello che finisce
    nella notifica, ma conservato — cosi' /bloccati puo' rileggerlo senza
    rifare nessun lookup. Una voce per IP: un secondo ban dello stesso
    indirizzo (dopo uno sblocco, o rientrato in una jail diversa)
    sovrascrive la precedente, perche' e' il ban PIU' RECENTE quello che
    conta per capire perche' e' bloccato adesso."""
    storico = _leggi_storico()
    storico[ip] = {
        "jail": jail,
        "motivo": motivo,
        "tentativi": tentativi,
        "path": principali,
        "status": status,
        "user_agent": ua,
        "geo": geo,
        "abuse": abuse,
        "quando": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if len(storico) > STORICO_MASSIMO:
        piu_vecchi = sorted(storico, key=lambda k: storico[k].get("quando", ""))
        for vecchio in piu_vecchi[:len(storico) - STORICO_MASSIMO]:
            storico.pop(vecchio, None)
    _scrivi_storico(storico)


def leggi_snapshot(ip):
    """Usata da /bloccati (script/photocarcifo-bot.py): la voce salvata
    per quell'IP, o None se non esiste (ban avvenuto prima che questo
    storico esistesse, o storico ripulito)."""
    return _leggi_storico().get(ip)


# ------------------------------------------------------------- lookup

def _http_json(url, timeout=TIMEOUT_LOOKUP, **header):
    try:
        req = urllib.request.Request(url, headers=header)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return None


def geolocalizza(ip):
    """Paese/regione/citta'/ISP/ASN/tipo rete. Nessun database GeoIP
    locale e' installato su questa macchina (MaxMind richiederebbe una
    licenza e un aggiornamento periodico del database per restare
    accurato) — si usa ip-api.com, che non richiede chiave per uso non
    commerciale a basso volume, con cache e timeout brevi cosi' un suo
    rallentamento non si sente da nessuna parte. Se anche questo dovesse
    sparire o cambiare condizioni, l'unico effetto e' un avviso con meno
    dettagli: il ban resta comunque valido.

    Ne' la citta' ne' la regione sono la posizione della persona: sono,
    quando va bene, quelle del data center/ISP che le assegna
    l'indirizzo — per questo compaiono sempre con l'accento sul dato di
    RETE, non sulla persona."""
    cache = _dalla_cache(ip)
    if cache and "geo" in cache:
        return cache["geo"]
    try:
        if ipaddress.ip_address(ip).is_private:
            return None
    except ValueError:
        return None
    dati = _http_json(
        f"http://ip-api.com/json/{urllib.parse.quote(ip)}"
        "?fields=status,country,regionName,city,isp,org,as,mobile,proxy,hosting")
    if not dati or dati.get("status") != "success":
        return None
    geo = {
        "country": dati.get("country") or None,
        "region": dati.get("regionName") or None,
        "city": dati.get("city") or None,
        "isp": dati.get("isp") or None,
        "org": dati.get("org") or None,
        "asn": (dati.get("as") or "").split(" ", 1)[0] or None,
        "rete": ("Datacenter/hosting" if dati.get("hosting")
                 else "Rete mobile" if dati.get("mobile")
                 else "Proxy/VPN noto" if dati.get("proxy") else None),
    }
    esistente = _dalla_cache(ip) or {}
    esistente["geo"] = geo
    _in_cache(ip, esistente)
    return geo


def reputazione(ip, api_key):
    """Punteggio abuso/segnalazioni da AbuseIPDB, SOLO se una chiave e'
    configurata: senza chiave la funzione non tenta nemmeno la
    richiesta. E' l'opposto di uno scraping HTML fragile — endpoint
    ufficiale, formato JSON stabile, e comunque mai un requisito: se
    l'API e' offline o la chiave manca, l'avviso esce lo stesso senza
    questa sezione."""
    if not api_key:
        return None
    cache = _dalla_cache(ip)
    if cache and "abuse" in cache:
        return cache["abuse"]
    dati = _http_json(
        f"https://api.abuseipdb.com/api/v2/check?ipAddress={urllib.parse.quote(ip)}"
        "&maxAgeInDays=90", Key=api_key, Accept="application/json")
    if not dati or "data" not in dati:
        return None
    d = dati["data"]
    abuse = {
        "score": d.get("abuseConfidenceScore"),
        "segnalazioni": d.get("totalReports"),
    }
    esistente = _dalla_cache(ip) or {}
    esistente["abuse"] = abuse
    _in_cache(ip, esistente)
    return abuse


# ------------------------------------------------------ crawler noti

# motore -> suffissi del reverse DNS ufficiale, come documentato dal motore stesso
#   Google: https://developers.google.com/search/docs/crawling-indexing/verifying-googlebot
#   Bing:   https://www.bing.com/webmasters/help/how-to-verify-bingbot-3905dc26
#   Apple:  https://support.apple.com/en-us/119829 (Applebot)
_SUFFISSI_MOTORI = {
    "Googlebot": (".googlebot.com.", ".google.com."),
    "Bingbot": (".search.msn.com.",),
    "Applebot": (".applebot.apple.com.",),
}

# Nomi di brand che compaiono spesso nel campo ISP/org di ip-api.com ma
# che NON provano niente da soli: quei cloud ospitano chiunque affitti
# una macchina virtuale, crawler ufficiali compresi ma anche chiunque
# altro. Serve solo per decidere quando vale la pena avvisare che il nome
# nel messaggio non e' garanzia di innocenza.
_BRAND_CLOUD_NOTI = ("microsoft", "google", "apple", "amazon", "aws",
                     "digitalocean", "ovh", "hetzner", "alibaba", "oracle")


def motore_verificato(ip):
    """Nome del crawler (Googlebot/Bingbot/Applebot) se l'indirizzo lo
    conferma con PTR+A, altrimenti None. Un indirizzo Microsoft/Azure o
    Google Cloud qualunque NON e' automaticamente Bingbot/Googlebot:
    quei cloud ospitano chiunque affitti una macchina virtuale, non solo
    i crawler dei motori di ricerca. La verifica corretta (quella che i
    motori stessi documentano) e' PTR+A: si chiede il nome host
    all'indirizzo (reverse DNS), si controlla che finisca nel dominio
    ufficiale del motore, poi si richiede di nuovo la risoluzione
    DIRETTA di quel nome e si controlla che torni allo stesso indirizzo
    di partenza — un solo passo (solo il reverse) si puo' falsificare
    con un PTR scritto a piacere su un server qualsiasi; il doppio
    controllo no, perche' richiederebbe controllare anche la zona DNS
    diretta del motore stesso."""
    import socket
    try:
        nome, _, _ = socket.gethostbyaddr(ip)
    except Exception:
        return None
    # gethostbyaddr non sempre include il punto finale del FQDN (dipende
    # dal resolver di sistema): lo si aggiunge per confrontare in forma
    # canonica senza dover duplicare ogni suffisso con/senza punto.
    if not nome.endswith("."):
        nome += "."
    for motore, suffissi in _SUFFISSI_MOTORI.items():
        if not any(nome.endswith(s) for s in suffissi):
            continue
        try:
            risolto = socket.gethostbyname(nome)
        except Exception:
            continue
        if risolto == ip:
            return motore
    return None


def brand_cloud_sospetto(geo):
    """True se il nome ISP/org somiglia a un grande cloud pubblico — usato
    SOLO per decidere se vale la pena avvisare che il nome da solo non
    prova niente, mai per giudicare se l'indirizzo e' malevolo (quello
    lo decide gia' fail2ban con il ban stesso)."""
    if not geo:
        return False
    testo = f"{geo.get('isp') or ''} {geo.get('org') or ''}".lower()
    return any(brand in testo for brand in _BRAND_CLOUD_NOTI)


def invia_telegram(config, testo):
    """Stesso bot amministrativo gia' in uso (app/telegram_avvisi.py,
    script/photocarcifo-bot.py): nessun secondo bot, stessa chat
    autorizzata, stesso file di configurazione."""
    token = leggi_env(config, "TELEGRAM_TOKEN")
    chat = leggi_env(config, "TELEGRAM_CHAT")
    if not (token and chat):
        return False
    try:
        corpo = urllib.parse.urlencode({
            "chat_id": chat, "text": testo, "disable_web_page_preview": "true",
        }).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage", data=corpo)
        with urllib.request.urlopen(req, timeout=8) as r:
            risposta = json.loads(r.read())
            return risposta.get("ok", False)
    except Exception as errore:
        loga(f"TELEGRAM fallito: {errore}")
        return False


# --------------------------------------------------------- escaping

def pulisci(testo, massimo=100):
    """Un path o uno User-Agent arrivano dall'esterno e finiscono in un
    messaggio di testo semplice (nessun parse_mode HTML/Markdown ne' su
    Telegram ne' su WhatsApp, coerente con telegram_avvisi.py): tolgo
    solo i caratteri di controllo/a capo, che romperebbero il formato a
    righe del messaggio — non serve altro escaping perche' il testo non
    viene mai interpretato come markup."""
    if not testo:
        return ""
    ripulito = "".join(c if c.isprintable() else " " for c in testo)
    ripulito = ripulito.replace("\n", " ").replace("\r", " ").strip()
    return ripulito[:massimo]


# --------------------------------------------------------- messaggio

def costruisci_messaggio(jail, ip, tentativi, righe, geo, abuse, motore, solo_avviso=None):
    """solo_avviso forza esplicitamente il titolo "solo avviso, nessun
    blocco" indipendentemente dal nome della jail — usato da
    photocarcifo-scansioni-decidi.py quando un indirizzo di
    photocarcifo-scansioni (jail che di norma banna per davvero) risulta
    hosting/datacenter e quindi non viene bloccato per quel motivo, non
    perche' la jail stessa sia "solo avviso". Se None (default), il
    comportamento e' quello di sempre: lo decide JAIL_SOLO_AVVISO in
    base al nome della jail."""
    motivo_base, livello = motivo_e_livello(jail)
    motivo = affina_motivo(motivo_base, righe)
    principali, status, ua = estrai_dettagli(righe)
    ora = datetime.now(timezone.utc).astimezone().strftime("%H:%M")

    if solo_avviso if solo_avviso is not None else jail in JAIL_SOLO_AVVISO:
        # Mai un ban vero in questo caso: il titolo deve dirlo, non un
        # generico "IP bannato" che farebbe credere a un blocco che non
        # e' mai scattato.
        righe_msg = ["🔍 Sito scansionato", f"IP: {ip}"]
    else:
        righe_msg = [f"🚫 IP BANNATO ({livello})" if livello == "CRITICAL" else "🚫 IP bannato",
                    f"IP: {ip}"]
    if motore:
        righe_msg.append(f"⚠️ Nota: reverse DNS confermato come {motore}, verificare prima di considerarlo malevolo")
    righe_msg.append(f"Motivo: {pulisci(motivo, 160)}")
    righe_msg.append(f"Tentativi: {tentativi}")
    if status:
        righe_msg.append(f"Ultimo status: {status}")
    if principali:
        righe_msg.append("Path:")
        righe_msg += [f"  {pulisci(p)}" for p in principali]
    if ua:
        righe_msg.append(f"User-Agent: {pulisci(ua)}")
    if geo:
        luogo = ", ".join(x for x in (geo.get("city"), geo.get("region"), geo.get("country")) if x)
        if luogo:
            righe_msg.append(f"🌍 {luogo} (indicativo: rete/ISP, non posizione reale)")
        if geo.get("isp") or geo.get("org"):
            righe_msg.append(f"ISP: {pulisci(geo.get('isp') or geo.get('org'), 80)}")
            # Il nome del cloud (Microsoft/Google/Apple/Amazon/...) non
            # prova che sia davvero quel servizio: sono datacenter che
            # ospitano chiunque affitti una VM, crawler compresi ma anche
            # tutti gli altri. Lo si chiarisce solo qui, quando non e'
            # gia' stato verificato sopra con PTR+A, per non far leggere
            # "ISP: Microsoft" come se fosse "questo e' Bing".
            if not motore and brand_cloud_sospetto(geo):
                righe_msg.append(
                    "ℹ️ È solo il nome del cloud che ospita l'indirizzo, non prova "
                    "che sia il servizio ufficiale — il reverse DNS non lo conferma")
        if geo.get("asn"):
            righe_msg.append(f"ASN: {pulisci(geo['asn'], 20)}")
        if geo.get("rete"):
            righe_msg.append(f"Rete: {geo['rete']}")
    if abuse and abuse.get("score") is not None:
        righe_msg.append(f"Reputazione: {abuse['score']}% abuse confidence")
        if abuse.get("segnalazioni"):
            righe_msg.append(f"Segnalazioni: {abuse['segnalazioni']}")
    righe_msg.append(f"Ora: {ora}")
    return "\n".join(righe_msg), livello


# ----------------------------------------------------- coda/raggruppamento

def accoda_messaggio(testo, livello):
    """Aggiunge un messaggio gia' pronto alla coda su disco. Un file
    JSONL (una riga JSON per messaggio) invece di un JSON unico: si
    accoda con un solo append, senza dover rileggere e riscrivere tutto
    il file ad ogni chiamata — importante perche' piu' ban ravvicinati
    chiamano questa funzione in processi paralleli diversi."""
    riga = json.dumps({"testo": testo, "livello": livello, "quando": time.time()})
    with open(CODA_TELEGRAM, "a") as f:
        f.write(riga + "\n")


def _svuota_coda():
    """Legge e cancella tutto il contenuto della coda in un colpo solo,
    sotto lock: chi chiama questa funzione deve gia' tenere CODA_LOCK,
    altrimenti due flush paralleli potrebbero dividersi i messaggi invece
    di raggrupparli tutti insieme."""
    p = Path(CODA_TELEGRAM)
    if not p.exists():
        return []
    testo = p.read_text()
    p.write_text("")
    eventi = []
    for riga in testo.splitlines():
        riga = riga.strip()
        if not riga:
            continue
        try:
            eventi.append(json.loads(riga))
        except json.JSONDecodeError:
            continue  # una riga corrotta si scarta, non deve far perdere le altre
    return eventi


# Limite reale di Telegram per sendMessage e' 4096 caratteri UTF-8;
# si resta sotto con un margine, cosi' l'intestazione aggiunta a ogni
# blocco (vedi sotto) non fa mai sforare per un pugno di byte.
LIMITE_TELEGRAM = 3800


def _messaggi_raggruppati(eventi):
    """Uno o piu' messaggi Telegram con dentro tutti gli eventi accodati:
    un solo messaggio raggruppato oltre LIMITE_TELEGRAM viene rifiutato
    da Telegram in blocco (HTTP 400), perdendo la notifica di TUTTI gli
    eventi che conteneva — scoperto il 31/08/2026 quando un ripristino
    di 11 ban dopo un riavvio della jail ha prodotto un unico messaggio
    troppo lungo, mai arrivato. Qui si spezza in piu' messaggi quando
    serve, ciascuno sotto il limite, invece di rischiare di perderli
    tutti per uno solo che sfora.

    Ritorna una lista di (testo, livello): il chiamante li invia in
    sequenza, uno per messaggio Telegram."""
    livello = "CRITICAL" if any(e.get("livello") == "CRITICAL" for e in eventi) else "WARNING"
    if len(eventi) == 1:
        return [(eventi[0]["testo"], eventi[0].get("livello", livello))]

    blocchi = []
    corrente = []
    lunghezza_corrente = 0
    for e in eventi:
        pezzo = e["testo"]
        # +2 per la riga vuota di separazione fra un evento e il successivo
        if corrente and lunghezza_corrente + len(pezzo) + 2 > LIMITE_TELEGRAM:
            blocchi.append(corrente)
            corrente = []
            lunghezza_corrente = 0
        corrente.append(pezzo)
        lunghezza_corrente += len(pezzo) + 2
    if corrente:
        blocchi.append(corrente)

    totale_parti = len(blocchi)
    messaggi = []
    for indice, blocco in enumerate(blocchi, start=1):
        intestazione = f"📋 {len(eventi)} avvisi ravvicinati ({livello})"
        if totale_parti > 1:
            intestazione += f" — parte {indice}/{totale_parti}"
        corpo = "\n\n".join(blocco)
        messaggi.append((f"{intestazione}\n\n{corpo}", livello))
    return messaggi


def _attendi_e_invia(config):
    """Gira in un processo staccato (vedi accoda_o_invia): aspetta la
    finestra di raggruppamento, poi svuota la coda e manda tutto insieme.
    Il lock resta preso per l'intera attesa, cosi' ogni altra chiamata
    nel frattempo si limita ad accodare (accoda_o_invia) invece di
    lanciare un secondo flush parallelo.

    Piu' di un messaggio se il gruppo supera il limite di Telegram (vedi
    _messaggi_raggruppati): si inviano tutti in sequenza, ciascuno
    loggato a parte, cosi' un invio fallito in mezzo agli altri non
    nasconde il fatto che gli altri sono comunque partiti."""
    time.sleep(FINESTRA_RAGGRUPPAMENTO)
    eventi = _svuota_coda()
    if not eventi:
        return
    messaggi = _messaggi_raggruppati(eventi)
    for indice, (testo, livello) in enumerate(messaggi, start=1):
        inviato = invia_telegram(config, testo)
        loga(f"INVIO raggruppato {indice}/{len(messaggi)} di {len(eventi)} evento/i "
            f"livello={livello} canale=telegram notificato={inviato}")


def accoda_o_invia(testo, livello, config):
    """Accoda il messaggio; se non c'e' gia' un invio raggruppato in
    corso per questa finestra, ne lancia uno nuovo (processo staccato,
    non blocca chi chiama). Il lock e' cio' che decide chi dei tanti
    processi fail2ban paralleli fa da "capofila" per il flush: il primo
    che arriva prende il lock e resta in attesa, tutti gli altri lo
    trovano gia' preso, si limitano ad accodare e tornano subito —
    fail2ban non deve mai aspettare la finestra di raggruppamento."""
    accoda_messaggio(testo, livello)

    lock_fd = os.open(CODA_LOCK, os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(lock_fd)
        return  # un altro processo e' gia' il capofila di questa finestra

    # Il lock resta tenuto dal PROCESSO FIGLIO staccato, non da questo:
    # se lo rilasciassimo qui prima di lanciarlo, un'altra chiamata
    # potrebbe prenderlo e lanciare un secondo flush in parallelo.
    # start_new_session stacca il figlio dal processo di fail2ban che ha
    # invocato questo script, cosi' quando fail2ban considera l'azione
    # conclusa (questo processo termina subito dopo) il figlio continua
    # a vivere per conto suo fino a fine attesa.
    pid = os.fork()
    if pid == 0:
        os.setsid()
        try:
            _attendi_e_invia(config)
        except Exception as errore:
            loga(f"ERRORE nel flush raggruppato: {errore!r}")
        finally:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(lock_fd)
            os._exit(0)
    else:
        os.close(lock_fd)  # il genitore non tiene il lock, l'ha preso il figlio


# --------------------------------------------------------------- main

def elabora(jail, ip, tentativi, righe, config=None, solo_avviso=None):
    """Tutta la logica, isolata da sys.argv/exit: cosi' i test la
    chiamano direttamente senza passare da un sottoprocesso.
    Ordine rispettato: il ban e' gia' avvenuto (e' fail2ban a chiamare
    questo script DOPO aver bannato), qui si arricchisce e si notifica,
    mai il contrario. Geo/whois/snapshot restano immediati (mai
    raggruppati): /bloccati deve vedere il ban appena avviene, e' solo
    l'invio Telegram che aspetta la finestra di raggruppamento.

    solo_avviso: vedi costruisci_messaggio — passato da
    photocarcifo-scansioni-decidi.py quando ha gia' deciso lui, guardando
    il tipo di rete, che questo evento non diventera' un blocco reale."""
    if config is None:
        config = leggi_config()

    try:
        ipaddress.ip_address(ip)
    except ValueError:
        loga(f"IP non valido ricevuto da fail2ban: {ip!r}")
        return False

    motore = motore_verificato(ip)
    geo = geolocalizza(ip)
    abuse = reputazione(ip, leggi_env(config, "ABUSEIPDB_API_KEY"))
    testo, livello = costruisci_messaggio(jail, ip, tentativi, righe, geo, abuse, motore, solo_avviso)

    # Lo snapshot si salva PRIMA della notifica: se invia_telegram()
    # fallisce o va lenta, /bloccati deve comunque poter leggere questi
    # dati — la persistenza non dipende dalla riuscita dell'invio.
    motivo_base, _ = motivo_e_livello(jail)
    motivo = affina_motivo(motivo_base, righe)
    principali, status, ua = estrai_dettagli(righe)
    salva_snapshot(jail, ip, tentativi, motivo, principali, status, ua, geo, abuse)

    # Stesso controllo che farebbe invia_telegram(): senza canale
    # configurato non c'e' niente da accodare ne' da inviare, e il
    # fork/attesa di accoda_o_invia() non ha motivo di partire.
    if not (leggi_env(config, "TELEGRAM_TOKEN") and leggi_env(config, "TELEGRAM_CHAT")):
        loga(f"BAN jail={jail} ip={ip} tentativi={tentativi} livello={livello} "
            f"canale=telegram accodato=False motivo=non_configurato")
        return False

    accoda_o_invia(testo, livello, config)
    loga(f"BAN jail={jail} ip={ip} tentativi={tentativi} livello={livello} "
        f"canale=telegram accodato=True")
    return True


def main():
    if len(sys.argv) < 4:
        print("uso: photocarcifo-ban-alert.py <jail> <ip> <tentativi> [righe-base64]",
              file=sys.stderr)
        sys.exit(0)  # exit 0 apposta: fail2ban non deve considerare questo un guasto del ban
    jail, ip, tentativi = sys.argv[1], sys.argv[2], sys.argv[3]
    righe = []
    if len(sys.argv) > 4 and sys.argv[4]:
        try:
            righe = base64.b64decode(sys.argv[4]).decode("utf-8", "replace").splitlines()
        except Exception:
            righe = []
    try:
        elabora(jail, ip, tentativi, righe)
    except Exception as errore:
        loga(f"ERRORE non gestito: {errore!r}")
    sys.exit(0)  # sempre 0: un guasto qui non deve mai riflettersi sul ban


if __name__ == "__main__":
    main()
