"""Avviso Telegram minimo per il modulo di contatto.

Riusa lo stesso bot amministrativo gia' configurato in
"/etc/photocarcifo-telegram.conf" (vedi script/photocarcifo-bot.py): stesso
file, stesso formato chiave=valore, nessuna variabile nuova. Qui non c'e'
nessun bot che ascolta, solo l'invio di un messaggio quando arriva una
richiesta di contatto dal sito.

Testo semplice, senza parse_mode: Telegram non richiede alcun escaping per
il testo semplice, ed e' l'unico modo per non doversi mai preoccupare di un
carattere che spezzi il formato HTML o Markdown.

Non deve mai far fallire chi lo chiama: qualunque problema (file assente,
token vuoto, rete che non risponde, Telegram che rifiuta) si traduce in un
semplice "no" silenzioso, con un avviso nei log.
"""
import urllib.parse
import urllib.request

from .database import log_event

CONFIG = "/etc/photocarcifo-telegram.conf"
_ATTESA = 10  # secondi


def _leggi_config(percorso: str = CONFIG):
    """Stesso parsing chiave=valore di script/photocarcifo-bot.py."""
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
        return "", ""
    return valori.get("TELEGRAM_TOKEN", ""), valori.get("TELEGRAM_CHAT", "")


def invia(testo: str, percorso_config: str = None) -> bool:
    """Manda un messaggio di testo semplice alla chat configurata.

    Ritorna True solo se Telegram ha risposto con successo. Qualunque altro
    caso (config assente, credenziali vuote, rete, risposta di errore)
    ritorna False senza sollevare eccezioni.
    """
    token, chat = _leggi_config(percorso_config or CONFIG)
    if not token or not chat:
        log_event("WARNING", "telegram", "Avviso non inviato: config assente o incompleta")
        return False
    try:
        corpo = urllib.parse.urlencode({"chat_id": chat, "text": testo}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage", data=corpo)
        with urllib.request.urlopen(req, timeout=_ATTESA) as r:
            if r.status != 200:
                log_event("WARNING", "telegram", f"Avviso non inviato: HTTP {r.status}")
                return False
            return True
    except Exception as errore:
        log_event("WARNING", "telegram", f"Avviso non inviato: {errore}")
        return False
