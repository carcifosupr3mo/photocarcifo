"""Recensioni lasciate da chi si e' fatto fotografare.

Chi ha lavorato con Photocarcifo puo' raccontarlo qui. Non serve
registrarsi: bastano un nome, un voto e due righe.

Le recensioni non compaiono subito. Restano in attesa finche' non vengono
approvate dal pannello: senza questo passaggio la pagina si riempirebbe di
pubblicita' automatica nel giro di poche settimane, come succede a
qualunque modulo aperto su internet.

Le difese contro l'invio automatico sono due e nessuna disturba chi scrive
davvero: un campo invisibile che solo i programmi compilano, e un tetto di
recensioni al giorno per collegamento. Un terzo controllo era stato
previsto — un tempo minimo fra l'apertura della pagina e l'invio — ma non
e' mai stato scritto: se serve va aggiunto qui, non solo nominato.
"""
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import lingue
from ..database import get_db, log_event
from ..deps import client_ip, get_current_user, require_admin_user, require_admin_api
from ..security import verify_csrf
from ..templating import templates

router = APIRouter()

VOTO_MIN, VOTO_MAX = 1, 5
NOME_MAX = 60
EVENTO_MAX = 80
TESTO_MIN, TESTO_MAX = 20, 1500

# Quante recensioni accettare dallo stesso collegamento in un giorno.
PER_GIORNO = 3


def _is_admin(request: Request) -> bool:
    u = get_current_user(request)
    return bool(u and u.get("is_admin"))


def _pubbliche(conn):
    return [dict(r) for r in conn.execute(
        "SELECT nome, voto, testo, evento, creato_at FROM recensioni "
        "WHERE approvata=1 ORDER BY creato_at DESC LIMIT 200").fetchall()]


def _media(righe):
    """Voto medio e numero di recensioni, per il riepilogo in cima."""
    if not righe:
        return None, 0
    return round(sum(r["voto"] for r in righe) / len(righe), 1), len(righe)


@router.get("/recensioni", response_class=HTMLResponse)
def pagina(request: Request, grazie: int = 0):
    with get_db() as conn:
        righe = _pubbliche(conn)
    media, quante = _media(righe)
    return templates.TemplateResponse(request, "public/recensioni.html", {"recensioni": righe, "media": media,
        "quante": quante, "grazie": bool(grazie), "errore": None,
        "is_admin": _is_admin(request)})


def _errore(request, chiave: str, stato: int = 400):
    """Ricarica la pagina spiegando cosa non andava, senza perdere nulla."""
    with get_db() as conn:
        righe = _pubbliche(conn)
    media, quante = _media(righe)
    testo = lingue.traduci(chiave, lingue.lingua_di(request))
    return templates.TemplateResponse(request, "public/recensioni.html", {"recensioni": righe, "media": media,
        "quante": quante, "grazie": False, "errore": testo,
        "is_admin": _is_admin(request)}, status_code=stato)


@router.post("/recensioni", response_class=HTMLResponse)
def invia(request: Request, nome: str = Form(""), voto: str = Form(""),
          testo: str = Form(""), evento: str = Form(""),
          sito: str = Form("")):
    # "sito" e' il campo invisibile: chi lo compila non e' una persona.
    if sito.strip():
        log_event("WARNING", "recensioni", "Invio automatico scartato")
        return RedirectResponse(url="/recensioni?grazie=1",
                                status_code=status.HTTP_303_SEE_OTHER)

    nome = " ".join(nome.split())[:NOME_MAX]
    evento = " ".join(evento.split())[:EVENTO_MAX]
    testo = testo.strip()[:TESTO_MAX]
    try:
        n_voto = int(voto)
    except (TypeError, ValueError):
        n_voto = 0

    if not nome:
        return _errore(request, "rec.err_nome")
    if not (VOTO_MIN <= n_voto <= VOTO_MAX):
        return _errore(request, "rec.err_voto")
    if len(testo) < TESTO_MIN:
        return _errore(request, "rec.err_testo")

    ip = client_ip(request)
    da = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    with get_db() as conn:
        recenti = conn.execute(
            "SELECT COUNT(*) c FROM recensioni WHERE ip=? AND creato_at>?",
            (ip, da)).fetchone()["c"]
        if recenti >= PER_GIORNO:
            return _errore(request, "rec.err_troppe", stato=429)
        conn.execute(
            "INSERT INTO recensioni (nome, voto, testo, evento, lingua, "
            "creato_at, approvata, ip) VALUES (?,?,?,?,?,?,0,?)",
            (nome, n_voto, testo, evento, lingue.lingua_di(request),
             datetime.now(timezone.utc).isoformat(), ip))
    log_event("INFO", "recensioni", f"Nuova recensione da {nome} ({n_voto}/5)")
    return RedirectResponse(url="/recensioni?grazie=1",
                            status_code=status.HTTP_303_SEE_OTHER)


# --- Pannello --------------------------------------------------------------

# Stato di una recensione, nella colonna "approvata":
#   0  in attesa, da decidere
#   1  pubblicata
#  -1  rifiutata: non si pubblica, ma non si butta
#
# Il rifiuto e' diverso dall'eliminazione. Eliminare cancella per sempre, e
# se la stessa persona riscrive non c'e' piu' modo di sapere che era gia'
# passata di qui. Rifiutare la toglie di mezzo lasciandone traccia, e si
# puo' sempre cambiare idea. Il valore -1 esce da solo da tutte le
# interrogazioni che esistevano prima, che cercano 0 oppure 1.
IN_ATTESA, PUBBLICATA, RIFIUTATA = 0, 1, -1


@router.get("/admin/recensioni", response_class=HTMLResponse)
def admin_pagina(request: Request, user: dict = Depends(require_admin_user)):
    with get_db() as conn:
        def elenco(stato):
            return [dict(r) for r in conn.execute(
                "SELECT * FROM recensioni WHERE approvata=? "
                "ORDER BY creato_at DESC", (stato,)).fetchall()]
        attesa, online, rifiutate = (elenco(IN_ATTESA), elenco(PUBBLICATA),
                                     elenco(RIFIUTATA))
    return templates.TemplateResponse(request, "admin/recensioni.html", {"user": user, "attesa": attesa, "online": online,
        "rifiutate": rifiutate})


@router.post("/admin/recensioni/{rec_id}/rifiuta")
def rifiuta(rec_id: int, csrf_token: str = Form(...),
            user: dict = Depends(require_admin_api)):
    """Non si pubblica, e non torna piu' nell'elenco di quelle da decidere."""
    if not verify_csrf(user.get("csrf", ""), csrf_token):
        raise HTTPException(status_code=403, detail="Sessione non valida")
    with get_db() as conn:
        conn.execute("UPDATE recensioni SET approvata=? WHERE id=?",
                     (RIFIUTATA, rec_id))
    log_event("INFO", "recensioni", f"Recensione {rec_id} rifiutata")
    return RedirectResponse(url="/admin/recensioni",
                            status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/recensioni/{rec_id}/approva")
def approva(rec_id: int, csrf_token: str = Form(...),
            user: dict = Depends(require_admin_api)):
    if not verify_csrf(user.get("csrf", ""), csrf_token):
        raise HTTPException(status_code=403, detail="Sessione non valida")
    with get_db() as conn:
        conn.execute("UPDATE recensioni SET approvata=1 WHERE id=?", (rec_id,))
    return RedirectResponse(url="/admin/recensioni",
                            status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/recensioni/{rec_id}/nascondi")
def nascondi(rec_id: int, csrf_token: str = Form(...),
             user: dict = Depends(require_admin_api)):
    if not verify_csrf(user.get("csrf", ""), csrf_token):
        raise HTTPException(status_code=403, detail="Sessione non valida")
    with get_db() as conn:
        conn.execute("UPDATE recensioni SET approvata=0 WHERE id=?", (rec_id,))
    return RedirectResponse(url="/admin/recensioni",
                            status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/recensioni/{rec_id}/elimina")
def elimina(rec_id: int, csrf_token: str = Form(...),
            user: dict = Depends(require_admin_api)):
    if not verify_csrf(user.get("csrf", ""), csrf_token):
        raise HTTPException(status_code=403, detail="Sessione non valida")
    with get_db() as conn:
        conn.execute("DELETE FROM recensioni WHERE id=?", (rec_id,))
    return RedirectResponse(url="/admin/recensioni",
                            status_code=status.HTTP_303_SEE_OTHER)
