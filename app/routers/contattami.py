"""Modulo pubblico per chi vuole scrivere e chiedere uno scatto.

Il sito non pubblica un indirizzo email o un numero di telefono: chi vuole
mettersi in contatto passa da qui. La richiesta finisce nel database e un
avviso arriva su Telegram (lo stesso bot amministrativo gia' in uso per gli
altri avvisi del sito, vedi app/telegram_avvisi.py), cosi' non serve
controllare un pannello per accorgersi che e' arrivato un messaggio.

Le difese contro l'invio automatico sono le stesse gia' viste in
recensioni.py: un campo invisibile che solo i programmi compilano, e un
tetto di richieste al giorno per indirizzo.
"""
import re
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Request, Form, status
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import lingue
from ..config import get_settings
from ..database import get_db, log_event
from ..deps import client_ip
from ..templating import templates
from .. import telegram_avvisi

router = APIRouter()

NOME_MAX = 100
EMAIL_MAX = 200
TELEFONO_MAX = 40
MESSAGGIO_MAX = 3000
DATA_EVENTO_MAX = 60
LUOGO_MAX = 100

# Quante richieste accettare dallo stesso indirizzo in un giorno. Stesso
# schema di recensioni.py (PER_GIORNO), tetto un po' piu' alto perche' un
# form di contatto legittimo puo' comportare un secondo invio dopo aver
# corretto un errore.
PER_GIORNO = 5

# Motivi ammessi: codice interno -> chiave di traduzione per l'etichetta.
# Codificati in inglese semplice perche' sono valori interni (finiscono nel
# database e nel pannello), le etichette mostrate arrivano da lingue.py.
MOTIVI = {
    "shooting_moto": "cont.motivo_moto",
    "shooting_auto": "cont.motivo_auto",
    "ritratto": "cont.motivo_ritratto",
    "evento": "cont.motivo_evento",
    "sport": "cont.motivo_sport",
    "collaborazione": "cont.motivo_collaborazione",
    "informazioni": "cont.motivo_informazioni",
    "altro": "cont.motivo_altro",
}

_RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _motivi_per_template(lingua: str) -> list:
    """Elenco (codice, etichetta) per popolare il menu del form."""
    return [(codice, lingue.traduci(chiave, lingua)) for codice, chiave in MOTIVI.items()]


@router.get("/contattami", response_class=HTMLResponse)
def pagina(request: Request, inviato: int = 0):
    lang = lingue.lingua_di(request)
    return templates.TemplateResponse(request, "public/contattami.html", {
        "motivi": _motivi_per_template(lang),
        "inviato": bool(inviato),
        "errore": None,
    })


def _errore(request, chiave: str, stato: int = 400):
    """Ricarica la pagina del modulo spiegando cosa non andava."""
    lang = lingue.lingua_di(request)
    testo = lingue.traduci(chiave, lang)
    return templates.TemplateResponse(request, "public/contattami.html", {
        "motivi": _motivi_per_template(lang),
        "inviato": False,
        "errore": testo,
    }, status_code=stato)


@router.post("/contattami", response_class=HTMLResponse)
def invia(request: Request, nome: str = Form(""), cognome: str = Form(""),
          email: str = Form(""), telefono: str = Form(""),
          motivo: str = Form(""), messaggio: str = Form(""),
          data_evento: str = Form(""), luogo: str = Form(""),
          sito_web: str = Form("")):
    # "sito_web" e' il campo invisibile: chi lo compila non e' una persona.
    if sito_web.strip():
        log_event("WARNING", "contattami", "Invio automatico scartato")
        return RedirectResponse(url="/contattami?inviato=1",
                                status_code=status.HTTP_303_SEE_OTHER)

    nome = " ".join(nome.split())[:NOME_MAX]
    cognome = " ".join(cognome.split())[:NOME_MAX]
    email = email.strip()[:EMAIL_MAX]
    telefono = " ".join(telefono.split())[:TELEFONO_MAX]
    motivo = motivo.strip()
    messaggio = messaggio.strip()[:MESSAGGIO_MAX]
    data_evento = " ".join(data_evento.split())[:DATA_EVENTO_MAX]
    luogo = " ".join(luogo.split())[:LUOGO_MAX]

    if not nome or not cognome:
        return _errore(request, "cont.err_nome")
    if not _RE_EMAIL.match(email):
        return _errore(request, "cont.err_email")
    if motivo not in MOTIVI:
        return _errore(request, "cont.err_motivo")
    if not messaggio:
        return _errore(request, "cont.err_messaggio")

    ip = client_ip(request)
    da = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    with get_db() as conn:
        recenti = conn.execute(
            "SELECT COUNT(*) c FROM richieste_contatto WHERE ip=? AND creato_at>?",
            (ip, da)).fetchone()["c"]
        if recenti >= PER_GIORNO:
            return _errore(request, "cont.err_troppe", stato=429)
        cur = conn.execute(
            "INSERT INTO richieste_contatto (nome, cognome, email, telefono, "
            "motivo, messaggio, data_evento, luogo, lingua, creato_at, "
            "stato, ip) VALUES (?,?,?,?,?,?,?,?,?,?,'Nuova',?)",
            (nome, cognome, email, telefono, motivo, messaggio, data_evento,
             luogo, lingue.lingua_di(request),
             datetime.now(timezone.utc).isoformat(), ip))
        richiesta_id = cur.lastrowid
    log_event("INFO", "contattami", f"Nuova richiesta da {nome} {cognome} ({motivo})")

    # L'avviso Telegram non deve mai poter far fallire la risposta al
    # cliente: la richiesta e' gia' salvata, questo e' solo un di piu'.
    try:
        _avvisa_telegram(richiesta_id, nome, cognome, email, telefono,
                         motivo, messaggio, data_evento, luogo)
    except Exception as errore:
        log_event("WARNING", "contattami", f"Avviso Telegram fallito: {errore}")

    return RedirectResponse(url="/contattami?inviato=1",
                            status_code=status.HTTP_303_SEE_OTHER)


def _avvisa_telegram(richiesta_id, nome, cognome, email, telefono, motivo,
                      messaggio, data_evento, luogo):
    settings = get_settings()
    righe = [
        "Nuova richiesta di contatto",
        f"{nome} {cognome}",
        f"Motivo: {motivo}",
        f"Email: {email}",
    ]
    if telefono:
        righe.append(f"Telefono: {telefono}")
    if data_evento:
        righe.append(f"Data evento: {data_evento}")
    if luogo:
        righe.append(f"Luogo: {luogo}")
    righe.append("")
    righe.append(messaggio)
    righe.append("")
    righe.append(f"{settings.site_url.rstrip('/')}/admin/richieste/{richiesta_id}")
    telegram_avvisi.invia("\n".join(righe))
