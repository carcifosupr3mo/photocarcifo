"""Calendario riservato dei raduni.

Pagina non collegata dal sito e non indicizzabile: vi si accede solo
conoscendo la risposta alla domanda impostata. Chi sbaglia troppe volte
viene bloccato per un periodo che raddoppia ogni volta, cosi' tentare a
caso diventa inutile.
"""
import time
from datetime import datetime
from urllib.parse import urlparse

from fastapi import APIRouter, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from itsdangerous import URLSafeTimedSerializer, BadSignature

from ..config import get_settings
from ..database import get_db, get_setting, set_setting, log_event
from ..deps import (client_ip, get_current_user, require_admin_user,
                    require_admin_api)
from ..security import hash_password, verify_password, verify_csrf, RateLimiter
from ..templating import templates

router = APIRouter()

COOKIE = "pc_raduni"
DURATA = 60 * 60 * 12
MAX_TENTATIVI = 5
BASE_ATTESA = 60

# Servizi di mappe accettati per il collegamento al luogo.
DOMINI_MAPPE = (
    "google.com", "google.ch", "google.it", "maps.google.com",
    "maps.app.goo.gl", "goo.gl", "openstreetmap.org", "osm.org",
    "maps.apple.com", "waze.com",
)


def mappa_valida(url: str) -> bool:
    """Accetta solo indirizzi di servizi di mappe conosciuti.

    Il controllo avviene sul dominio vero e non sul testo: un indirizzo
    come evil.com/google.com/maps viene respinto."""
    if not url or not url.strip():
        return True
    try:
        p = urlparse(url.strip())
    except ValueError:
        return False
    if p.scheme != "https" or not p.netloc:
        return False
    host = p.netloc.lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return any(host == d or host.endswith("." + d) for d in DOMINI_MAPPE)

# Il conteggio dei tentativi sta nel database, non nella memoria del
# processo: con piu' processi in parallelo ognuno terrebbe il proprio, e
# chi prova a indovinare la risposta avrebbe cinque tentativi per processo
# invece di cinque in tutto. Vedi security.RateLimiter.
_conteggio = RateLimiter("raduni", max_attempts=MAX_TENTATIVI,
                         window_seconds=6 * 3600)


def _indirizzo(request: Request) -> str:
    """Indirizzo di chi sta provando a entrare.

    Si usa lo stesso metodo del login (X-Real-IP, che Nginx riempie da solo
    con l'indirizzo vero della connessione). NON si guarda
    X-Forwarded-For: Nginx si limita ad accodarvi l'indirizzo reale, quindi
    la prima voce e' scritta dal visitatore. Prendendo quella, bastava
    cambiarla a ogni tentativo per non venire mai bloccati e provare la
    risposta all'infinito.
    """
    return client_ip(request)


def _attesa_per(quanti: int) -> int:
    """Quanto deve aspettare chi ha sbagliato tante volte.

    I primi errori non costano niente: capita di ricordare male. Dal quinto
    in poi l'attesa raddoppia ogni volta — un minuto, due, quattro — fino a
    un'ora. Chi prova a indovinare si ferma da solo dopo pochi giri, chi ha
    solo sbagliato aspetta un minuto e riprova.
    """
    if quanti < MAX_TENTATIVI:
        return 0
    return int(min(BASE_ATTESA * (2 ** (quanti - MAX_TENTATIVI)), 3600))


def _bloccato(ip: str) -> int:
    """Secondi che mancano prima di poter riprovare, 0 se si puo' subito."""
    from ..database import get_db
    try:
        with get_db() as conn:
            riga = conn.execute(
                "SELECT COUNT(*) AS quanti, MAX(quando) AS ultimo "
                "FROM tentativi WHERE ambito='raduni' AND chiave=? "
                "AND quando > ?",
                (ip, time.time() - 6 * 3600)).fetchone()
    except Exception:
        return 0
    quanti = riga["quanti"] or 0
    if quanti < MAX_TENTATIVI:
        return 0
    passati = time.time() - (riga["ultimo"] or 0)
    return max(0, int(_attesa_per(quanti) - passati))


def _segna_errore(ip: str) -> int:
    """Registra l'errore e restituisce quanto si deve aspettare adesso."""
    _conteggio.hit(ip)
    return _bloccato(ip)


def _azzera(ip: str) -> None:
    _conteggio.reset(ip)


def _quanti_bloccati() -> int:
    """Quanti indirizzi stanno aspettando adesso. Si mostra nel pannello."""
    from ..database import get_db
    try:
        with get_db() as conn:
            righe = conn.execute(
                "SELECT chiave FROM tentativi WHERE ambito='raduni' "
                "AND quando > ? GROUP BY chiave HAVING COUNT(*) >= ?",
                (time.time() - 6 * 3600, MAX_TENTATIVI)).fetchall()
    except Exception:
        return 0
    return sum(1 for r in righe if _bloccato(r["chiave"]))


def _svuota_tentativi() -> int:
    """Toglie il blocco a tutti. Restituisce quanti erano.

    Serve al pannello: quando si cambia la risposta, chi era rimasto fuori
    con quella vecchia non deve continuare ad aspettare per una domanda
    che non esiste piu'."""
    from ..database import get_db
    try:
        with get_db() as conn:
            quanti = conn.execute(
                "SELECT COUNT(DISTINCT chiave) c FROM tentativi "
                "WHERE ambito='raduni'").fetchone()["c"]
            conn.execute("DELETE FROM tentativi WHERE ambito='raduni'")
            return quanti
    except Exception:
        return 0


def _serializer():
    return URLSafeTimedSerializer(get_settings().secret_key, salt="raduni")


def _ha_accesso(request: Request) -> bool:
    u = get_current_user(request)
    if u and u.get("is_admin"):
        return True
    token = request.cookies.get(COOKIE)
    if not token:
        return False
    try:
        return _serializer().loads(token, max_age=DURATA).get("ok") is True
    except (BadSignature, Exception):
        return False


def _domanda() -> str:
    return get_setting("raduni_domanda", "Dove si trova il prossimo raduno?")


def _avviso() -> str:
    return get_setting(
        "raduni_avviso",
        "Non sono organizzatore ne' affiliato ai raduni elencati. "
        "Partecipo esclusivamente come fotografo per documentare gli eventi. "
        "Ogni partecipante e' responsabile della propria condotta e del "
        "rispetto del codice della strada.")


def _prossimi():
    with get_db() as conn:
        righe = conn.execute(
            "SELECT id, data, ora, luogo, note, mappa FROM raduni "
            "WHERE data >= date('now') ORDER BY data, ora").fetchall()
    return [dict(r) for r in righe]


def _passati():
    with get_db() as conn:
        righe = conn.execute(
            "SELECT id, data, ora, luogo, note, mappa FROM raduni "
            "WHERE data < date('now') ORDER BY data DESC LIMIT 12").fetchall()
    return [dict(r) for r in righe]


@router.get("/radunimoto", response_class=HTMLResponse)
def pagina(request: Request):
    if not _ha_accesso(request):
        return templates.TemplateResponse(request, "public/raduni_accesso.html", {"domanda": _domanda(),
            "errore": None, "attesa": _bloccato(_indirizzo(request))})
    return templates.TemplateResponse(request, "public/raduni.html", {"avviso": _avviso(),
        "prossimi": _prossimi(), "passati": _passati(),
        "is_admin": bool((get_current_user(request) or {}).get("is_admin"))})


@router.post("/radunimoto", response_class=HTMLResponse)
def accedi(request: Request, risposta: str = Form(...)):
    ip = _indirizzo(request)

    attesa = _bloccato(ip)
    if attesa:
        return templates.TemplateResponse(request, "public/raduni_accesso.html", {"domanda": _domanda(),
            "errore": f"Troppi tentativi. Riprova fra {attesa} secondi.",
            "attesa": attesa}, status_code=status.HTTP_429_TOO_MANY_REQUESTS)

    salvata = get_setting("raduni_risposta_hash", "")
    corretta = bool(salvata) and verify_password(risposta.strip().lower(), salvata)

    if not corretta:
        nuova = _segna_errore(ip)
        log_event("WARNING", "raduni", f"Risposta errata da {ip}")
        messaggio = ("Risposta non corretta." if not nuova
                     else f"Troppi tentativi. Riprova fra {nuova} secondi.")
        return templates.TemplateResponse(request, "public/raduni_accesso.html", {"domanda": _domanda(),
            "errore": messaggio, "attesa": nuova},
            status_code=status.HTTP_401_UNAUTHORIZED)

    _azzera(ip)
    log_event("INFO", "raduni", f"Accesso riuscito da {ip}")
    risposta_http = RedirectResponse(url="/radunimoto",
                                     status_code=status.HTTP_303_SEE_OTHER)
    risposta_http.set_cookie(COOKIE, _serializer().dumps({"ok": True}),
                             max_age=DURATA, httponly=True,
                             samesite="lax", secure=True, path="/")
    return risposta_http


def _maschera(ip: str) -> str:
    """Mostra solo la parte iniziale dell'indirizzo.

    Serve a capire quante persone diverse accedono senza conservare in
    chiaro un dato che identifica qualcuno."""
    parti = ip.split(".")
    if len(parti) == 4:
        return f"{parti[0]}.{parti[1]}.x.x"
    return ip[:10] + "…" if len(ip) > 10 else ip


def _statistiche():
    """Chi ha aperto il calendario, in forma aggregata."""
    estrai = "replace(message, 'Accesso riuscito da ', '')"
    with get_db() as conn:
        def uno(q):
            r = conn.execute(q).fetchone()
            return r[0] if r else 0

        totali = uno("SELECT COUNT(*) FROM logs WHERE category='raduni' "
                     "AND message LIKE 'Accesso riuscito%'")
        persone = uno(f"SELECT COUNT(DISTINCT {estrai}) FROM logs "
                      "WHERE category='raduni' AND message LIKE 'Accesso riuscito%'")
        settimana = uno(f"SELECT COUNT(DISTINCT {estrai}) FROM logs "
                        "WHERE category='raduni' AND message LIKE 'Accesso riuscito%' "
                        "AND ts > datetime('now','-7 days')")
        oggi = uno("SELECT COUNT(*) FROM logs WHERE category='raduni' "
                   "AND message LIKE 'Accesso riuscito%' "
                   "AND ts > datetime('now','-1 day')")
        falliti = uno("SELECT COUNT(*) FROM logs WHERE category='raduni' "
                      "AND message LIKE 'Risposta errata%' "
                      "AND ts > datetime('now','-30 days')")

        righe = conn.execute(
            f"SELECT {estrai} AS chi, COUNT(*) AS quante, MAX(ts) AS ultimo "
            "FROM logs WHERE category='raduni' AND message LIKE 'Accesso riuscito%' "
            "GROUP BY chi ORDER BY ultimo DESC LIMIT 25").fetchall()

    elenco = [{"chi": _maschera(r["chi"]), "quante": r["quante"],
               "ultimo": (r["ultimo"] or "")[:16].replace("T", " ")}
              for r in righe]
    return {"totali": totali, "persone": persone, "settimana": settimana,
            "oggi": oggi, "falliti": falliti, "elenco": elenco}


@router.get("/admin/raduni", response_class=HTMLResponse)
def admin_pagina(request: Request, user: dict = Depends(require_admin_user)):
    with get_db() as conn:
        righe = conn.execute(
            "SELECT id, data, ora, luogo, note, mappa FROM raduni "
            "ORDER BY data DESC").fetchall()
    return templates.TemplateResponse(request, "admin/raduni.html", {"user": user, "raduni": [dict(r) for r in righe],
        "domanda": _domanda(), "avviso": _avviso(),
        "risposta_impostata": bool(get_setting("raduni_risposta_hash", "")),
        "bloccati": _quanti_bloccati(),
        "stat": _statistiche()})


@router.post("/admin/raduni/aggiungi")
def aggiungi(csrf_token: str = Form(...), data: str = Form(...),
             ora: str = Form(""), luogo: str = Form(...), note: str = Form(""),
             mappa: str = Form(""),
             user: dict = Depends(require_admin_api)):
    if not verify_csrf(user.get("csrf", ""), csrf_token):
        raise HTTPException(status_code=403, detail="Sessione non valida")
    try:
        datetime.strptime(data, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Data non valida")
    if not mappa_valida(mappa):
        raise HTTPException(
            status_code=400,
            detail="Collegamento non valido: usa un indirizzo di Google Maps, "
                   "Apple Maps, OpenStreetMap o Waze che inizi con https://")
    with get_db() as conn:
        conn.execute(
            "INSERT INTO raduni(data, ora, luogo, note, mappa, creato) "
            "VALUES(?,?,?,?,?,datetime('now'))",
            (data, ora.strip()[:20], luogo.strip()[:200], note.strip()[:500],
             mappa.strip()[:500] or None))
    log_event("INFO", "raduni", f"Aggiunto raduno del {data}")
    return JSONResponse({"ok": True})


@router.post("/admin/raduni/{raduno_id}/elimina")
def elimina(raduno_id: int, csrf_token: str = Form(...),
            user: dict = Depends(require_admin_api)):
    if not verify_csrf(user.get("csrf", ""), csrf_token):
        raise HTTPException(status_code=403, detail="Sessione non valida")
    with get_db() as conn:
        conn.execute("DELETE FROM raduni WHERE id=?", (raduno_id,))
    return JSONResponse({"ok": True})


@router.post("/admin/raduni/impostazioni")
def impostazioni(csrf_token: str = Form(...), domanda: str = Form(""),
                 risposta: str = Form(""), avviso: str = Form(""),
                 user: dict = Depends(require_admin_api)):
    """Cambia domanda, risposta e testo dell'avviso."""
    if not verify_csrf(user.get("csrf", ""), csrf_token):
        raise HTTPException(status_code=403, detail="Sessione non valida")
    if domanda.strip():
        set_setting("raduni_domanda", domanda.strip()[:300])
    if avviso.strip():
        set_setting("raduni_avviso", avviso.strip()[:1500])
    cambiata = False
    if risposta.strip():
        set_setting("raduni_risposta_hash",
                    hash_password(risposta.strip().lower()))
        _svuota_tentativi()
        cambiata = True
        log_event("INFO", "raduni", "Risposta di accesso aggiornata")
    return JSONResponse({"ok": True, "risposta_cambiata": cambiata})


@router.post("/admin/raduni/sblocca")
def sblocca(csrf_token: str = Form(...),
            user: dict = Depends(require_admin_api)):
    if not verify_csrf(user.get("csrf", ""), csrf_token):
        raise HTTPException(status_code=403, detail="Sessione non valida")
    quanti = _svuota_tentativi()
    return JSONResponse({"ok": True, "sbloccati": quanti})


@router.post("/admin/raduni/{raduno_id}/mappa")
def modifica_mappa(raduno_id: int, csrf_token: str = Form(...),
                   mappa: str = Form(""),
                   user: dict = Depends(require_admin_api)):
    """Aggiunge o cambia il collegamento alle mappe di un appuntamento."""
    if not verify_csrf(user.get("csrf", ""), csrf_token):
        raise HTTPException(status_code=403, detail="Sessione non valida")
    if not mappa_valida(mappa):
        raise HTTPException(
            status_code=400,
            detail="Collegamento non valido: usa Google Maps, Apple Maps, "
                   "OpenStreetMap o Waze, con indirizzo che inizia per https://")
    with get_db() as conn:
        conn.execute("UPDATE raduni SET mappa=? WHERE id=?",
                     (mappa.strip()[:500] or None, raduno_id))
    return JSONResponse({"ok": True})
