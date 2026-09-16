"""Dependency injection per autenticazione e contesto di richiesta.

Fornisce dipendenze FastAPI riutilizzabili per:
- ricavare l'utente corrente dal cookie di sessione;
- proteggere le rotte admin (redirect al login se non autenticato);
- esporre il token CSRF alla request;
- ricavare l'IP client reale (dietro Nginx via X-Real-IP).

Centralizzare questa logica evita duplicazioni nei router.
"""
from typing import Optional

from fastapi import Request, HTTPException, status
from fastapi.responses import RedirectResponse

from .database import get_db
from .security import read_session

SESSION_COOKIE = "pc_session"


# Da chi si accetta l'intestazione che dichiara l'indirizzo del visitatore:
# solo nginx, che gira sulla stessa macchina.
_PROXY_FIDATI = {"127.0.0.1", "::1", "localhost"}


def client_ip(request: Request) -> str:
    """Indirizzo reale del visitatore.

    Nginx lo inoltra in X-Real-IP, sovrascrivendo quello che il visitatore
    avesse eventualmente scritto di suo. Qui pero' l'intestazione si accetta
    solo se la richiesta arriva davvero da nginx: su questo dato poggiano il
    conteggio dei tentativi di accesso ai raduni, il tetto di recensioni al
    giorno e i registri di sicurezza, e chi potesse dettarlo a piacere li
    aggirerebbe tutti scrivendo un indirizzo diverso a ogni tentativo.

    Oggi l'applicazione ascolta solo su 127.0.0.1, quindi da fuori non ci si
    arriva comunque. Il controllo serve perche' quella condizione non resti
    l'unica cosa che protegge: basterebbe aprire la porta un giorno per
    diagnosticare qualcosa e la difesa cadrebbe in silenzio.
    """
    diretto = request.client.host if request.client else ""
    if diretto in _PROXY_FIDATI:
        inoltrato = request.headers.get("x-real-ip")
        if inoltrato:
            # Si tiene il primo della catena e si tronca: e' testo che
            # arriva da fuori e finisce nei registri e nel database.
            return inoltrato.split(",")[0].strip()[:64]
    return diretto or "sconosciuto"


def get_session(request: Request) -> Optional[dict]:
    """Decodifica il cookie di sessione (o None se assente/non valido)."""
    token = request.cookies.get(SESSION_COOKIE)
    return read_session(token)


def get_current_user(request: Request) -> Optional[dict]:
    """Restituisce l'utente autenticato come dict, oppure None.

    Legge la sessione, verifica che l'utente esista ancora nel DB
    (es. non sia stato eliminato) e ne ritorna i dati essenziali.
    """
    session = get_session(request)
    if not session:
        return None
    uid = session.get("uid")
    if not uid:
        return None
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, username, is_admin FROM users WHERE id=?", (uid,)
        ).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "username": row["username"],
        "is_admin": bool(row["is_admin"]),
        "csrf": session.get("csrf", ""),
    }


class _RedirectToLogin(Exception):
    """Eccezione interna: intercettata da un exception handler globale
    per reindirizzare al login le pagine admin non autenticate."""
    pass


class RequireAdmin:
    """Dependency che protegge le rotte della dashboard.

    Se l'utente non e autenticato:
    - per richieste "pagina" (GET HTML) reindirizza a /admin/login;
    - per richieste API/POST solleva 401.

    Uso nei router:
        user = Depends(require_admin_user)   # pagine HTML
        user = Depends(require_admin_api)    # endpoint API/POST
    """
    def __init__(self, api: bool = False):
        self.api = api

    def __call__(self, request: Request) -> dict:
        user = get_current_user(request)
        if user and user["is_admin"]:
            return user
        if self.api:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Autenticazione richiesta",
            )
        raise _RedirectToLogin()


# Istanze pronte all'uso come dipendenze
require_admin_user = RequireAdmin(api=False)   # pagine HTML
require_admin_api = RequireAdmin(api=True)     # endpoint API/POST


def redirect_to_login() -> RedirectResponse:
    """Helper per costruire il redirect al login."""
    return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
