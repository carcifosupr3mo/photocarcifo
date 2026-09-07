"""Avviso IndexNow: dice a Bing (e agli altri motori che aderiscono allo
stesso protocollo) che una URL pubblica e' cambiata, cosi' la ripassano a
controllare prima del prossimo giro di scansione normale, invece che dopo
settimane.

Stesso spirito di telegram_avvisi.py: un modulo piccolo, che non deve mai
far fallire chi lo chiama. Qualunque problema (chiave assente, rete che non
risponde, IndexNow che rifiuta) si traduce in un "no" silenzioso con un
avviso nei log, mai in un'eccezione che arriva a chi ha chiesto di
pubblicare un album.

La chiave NON e' un segreto nel senso classico: lo standard IndexNow la
richiede leggibile da chiunque, proprio all'indirizzo pubblico
https://photocarcifo.ch/<chiave>.txt (vedi routers/seo.py:indexnow_key),
cosi' il motore di ricerca puo' verificare che chi manda la notifica sia
davvero il proprietario del sito. Va comunque generata una volta e restare
stabile: cambiarla di continuo obbligherebbe a rifare la verifica a ogni
notifica.
"""
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from urllib.parse import unquote, urlsplit

from . import lingue
from .config import get_settings
from .database import log_event

ENDPOINT = "https://api.indexnow.org/indexnow"
_ATTESA = 5  # secondi: non deve mai far aspettare una richiesta utente a lungo
_MAX_URLS_PER_CHIAMATA = 10000  # limite dichiarato dal protocollo IndexNow


def _dominio_consentito(url: str, base: str) -> bool:
    """Vero solo se url appartiene esattamente al dominio del sito.

    Confronto sull'host, non un prefisso di stringa: senza, un sito ospite
    su "https://photocarcifo.ch.evil.example/" supererebbe un controllo
    fatto con str.startswith(base). Qui invece si spacca l'indirizzo e si
    guardano schema+host, l'unico modo corretto di dire "e' questo sito".
    """
    try:
        u, b = urlsplit(url), urlsplit(base)
        return bool(u.scheme and u.netloc) and (u.scheme, u.netloc) == (b.scheme, b.netloc)
    except ValueError:
        return False


# Segmenti che rendono una URL non adatta a una notifica di indicizzazione:
# pannello, API, autenticazione, file interni, scaricamenti, miniature,
# album/foto riservati, pagine gia' segnate noindex. La stessa lista di
# concetti di robots.txt (vedi seo.py:robots), qui applicata a un singolo
# indirizzo invece che come regola per un crawler.
_SEGMENTI_ESCLUSI = (
    "/admin", "/api/", "/login", "/logout", "/2fa", "/p/", "/f/", "/fs/",
    "/download/", "/zip/", "/video/", "/thumb/", "/thumb2x/", "/cover/",
    "/preview/", "/preferiti/", "/mie-preferite",
    "/lingua/", "/healthz", "/search",
)


def url_indicizzabile(url: str) -> bool:
    """Vero solo se questa URL e' il tipo di pagina pubblica che ha senso
    notificare: stesso dominio, nessun segmento tecnico/riservato, nessuna
    query string (le pagine con parametri, ?page=, ?ordine=, ?q=..., non
    sono mai quelle canoniche indicizzabili — vedi node.html/home.html)."""
    settings = get_settings()
    base = settings.site_url.rstrip("/")
    if not _dominio_consentito(url, base):
        return False
    parsed = urlsplit(url)
    if parsed.query:
        return False

    # Normalizzato prima del confronto: decodificato una volta (%2F ecc.),
    # senza doppie barre, senza segmenti "." — cosi' un indirizzo scritto
    # in un modo insolito (maiuscole, barra doppia, percent-encoding) non
    # riesce a passare per un'altra strada quello che _SEGMENTI_ESCLUSI
    # blocca nella forma normale. Oggi le uniche chiamate a questa funzione
    # arrivano da URL costruite dal codice stesso (mai da un indirizzo
    # scritto da un visitatore), quindi non e' una falla sfruttabile adesso
    # — resta comunque la barriera giusta da avere, non solo un dettaglio,
    # nel caso in futuro qualcosa la chiami con un indirizzo meno fidato.
    grezzo = re.sub(r"/{2,}", "/", unquote(parsed.path))
    path = os.path.normpath(grezzo).lower()
    if not path.startswith("/"):
        path = "/" + path
    if path == "/.":
        path = "/"

    # Stesso elenco di lingue di seo.py:robots() (lingue.PREFISSI). Il
    # prefisso va tolto dall'INIZIO del path prima del confronto, non
    # cercato come sottostringa in un punto qualsiasi: un album il cui
    # slug contenesse per caso "it/download" nel mezzo dell'indirizzo (o
    # qualunque altra coincidenza) non deve essere scartato per errore.
    senza_lingua = path
    for codice in lingue.PREFISSI:
        prefisso = f"/{codice}"
        if path == prefisso or path.startswith(prefisso + "/"):
            senza_lingua = path[len(prefisso):] or "/"
            break
    return not any(senza_lingua.startswith(s) for s in _SEGMENTI_ESCLUSI)


def _leggi_chiave() -> str:
    """La chiave vive in .env come le altre impostazioni del sito (vedi
    config.py:indexnow_key), non in un file a parte: e' un solo valore,
    stabile, non un segreto da proteggere con permessi diversi dal resto
    della configurazione."""
    return (get_settings().indexnow_key or "").strip()


def notify_indexnow(urls, percorso_config=None) -> bool:
    """Notifica IndexNow di una o piu' URL cambiate.

    Filtra, deduplica, scarta cio' che non appartiene al sito o non e'
    indicizzabile, e nel caso di piu' URL usa la chiamata in batch prevista
    dal protocollo invece di una chiamata per indirizzo. Ritorna True solo
    se la notifica e' stata davvero inviata con successo; False in ogni
    altro caso (incluso "non c'era nulla di valido da inviare"), senza mai
    sollevare eccezioni.
    """
    chiave = _leggi_chiave()
    if not chiave:
        log_event("WARNING", "indexnow", "Notifica non inviata: chiave assente")
        return False

    if isinstance(urls, str):
        urls = [urls]
    settings = get_settings()
    base = settings.site_url.rstrip("/")
    host = urlsplit(base).netloc

    # dict.fromkeys invece di set(): elimina i duplicati mantenendo l'ordine
    # originale, comodo per capire dai log cosa e' stato davvero mandato.
    pulite = list(dict.fromkeys(u for u in urls if u and url_indicizzabile(u)))
    if not pulite:
        return False
    if len(pulite) > _MAX_URLS_PER_CHIAMATA:
        pulite = pulite[:_MAX_URLS_PER_CHIAMATA]

    corpo = json.dumps({
        "host": host,
        "key": chiave,
        "keyLocation": f"{base}/{chiave}.txt",
        "urlList": pulite,
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            ENDPOINT, data=corpo, method="POST",
            headers={"Content-Type": "application/json; charset=utf-8"})
        with urllib.request.urlopen(req, timeout=_ATTESA) as r:
            # IndexNow risponde 200 o 202 per un invio accettato.
            if r.status not in (200, 202):
                log_event("WARNING", "indexnow", f"Notifica rifiutata: HTTP {r.status}")
                return False
            log_event("INFO", "indexnow", f"Notificate {len(pulite)} URL")
            return True
    except urllib.error.HTTPError as errore:
        log_event("WARNING", "indexnow", f"Notifica non inviata: HTTP {errore.code}")
        return False
    except Exception as errore:
        log_event("WARNING", "indexnow", f"Notifica non inviata: {errore}")
        return False
