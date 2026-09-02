"""Autenticazione a due fattori (TOTP) per l'account amministratore."""
import base64
import io

import pyotp
import qrcode
from fastapi import APIRouter, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse

from ..database import get_db, log_event
from ..deps import require_admin_user, require_admin_api, client_ip
from ..security import (verify_csrf, verify_password, dimentica_dispositivi,
                        totp_limiter)
from ..templating import templates

router = APIRouter(prefix="/admin/2fa")


def _check_csrf(user, tok):
    if not verify_csrf(user.get("csrf", ""), tok):
        raise HTTPException(status_code=403, detail="CSRF non valido")


def _qr_data_uri(uri: str) -> str:
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


@router.get("", response_class=HTMLResponse)
def page(request: Request, user: dict = Depends(require_admin_user)):
    with get_db() as conn:
        row = conn.execute("SELECT totp_secret, totp_enabled FROM users WHERE id=?",
                           (user["id"],)).fetchone()
    enabled = bool(row and row["totp_enabled"])
    qr = None
    secret = None
    if not enabled:
        secret = (row["totp_secret"] if row and row["totp_secret"] else pyotp.random_base32())
        with get_db() as conn:
            conn.execute("UPDATE users SET totp_secret=? WHERE id=?", (secret, user["id"]))
        uri = pyotp.TOTP(secret).provisioning_uri(
            name=user["username"], issuer_name="Photocarcifo")
        qr = _qr_data_uri(uri)
    return templates.TemplateResponse(request, "admin/twofa.html", {"user": user, "enabled": enabled,
        "qr": qr, "secret": secret, "error": None})


@router.post("/enable")
def enable(request: Request, csrf_token: str = Form(...), code: str = Form(...),
           user: dict = Depends(require_admin_api)):
    _check_csrf(user, csrf_token)
    # Sei cifre si indovinano in fretta: stesso freno del login, cosi' una
    # sessione rubata non basta per forzare il codice a tentativi.
    if not totp_limiter.check(client_ip(request)):
        raise HTTPException(status_code=429, detail="Troppi tentativi")
    with get_db() as conn:
        row = conn.execute("SELECT totp_secret FROM users WHERE id=?", (user["id"],)).fetchone()
        if not row or not row["totp_secret"]:
            raise HTTPException(status_code=400, detail="Nessun segreto generato")
        if not pyotp.TOTP(row["totp_secret"]).verify(code.strip(), valid_window=1):
            totp_limiter.hit(client_ip(request))
            log_event("WARNING", "auth", "Codice 2FA errato in attivazione")
            return RedirectResponse(url="/admin/2fa?err=1", status_code=status.HTTP_303_SEE_OTHER)
        totp_limiter.reset(client_ip(request))
        conn.execute("UPDATE users SET totp_enabled=1 WHERE id=?", (user["id"],))
    log_event("INFO", "auth", f"2FA attivato per {user['username']}")
    return RedirectResponse(url="/admin/2fa", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/disable")
def disable(request: Request, csrf_token: str = Form(...), password: str = Form(...),
            user: dict = Depends(require_admin_api)):
    _check_csrf(user, csrf_token)
    if not totp_limiter.check(client_ip(request)):
        raise HTTPException(status_code=429, detail="Troppi tentativi")
    with get_db() as conn:
        row = conn.execute("SELECT password_hash FROM users WHERE id=?", (user["id"],)).fetchone()
        if not row or not verify_password(password, row["password_hash"]):
            totp_limiter.hit(client_ip(request))
            log_event("WARNING", "auth", "Password errata in disattivazione 2FA")
            return RedirectResponse(url="/admin/2fa?err=2", status_code=status.HTTP_303_SEE_OTHER)
        totp_limiter.reset(client_ip(request))
        conn.execute("UPDATE users SET totp_enabled=0, totp_secret=NULL WHERE id=?", (user["id"],))
    log_event("INFO", "auth", f"2FA disattivato per {user['username']}")
    return RedirectResponse(url="/admin/2fa", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/dimentica-dispositivi")
def dimentica(request: Request, csrf_token: str = Form(...),
              user: dict = Depends(require_admin_api)):
    """Sgancia tutti i dispositivi che restavano collegati.

    Serve in un caso solo, ma e' il caso che conta: un telefono perso o
    prestato. Senza questo l'unico modo di annullare una sessione lunga
    sarebbe cambiare la chiave di firma del sito, che pero' butta fuori
    anche i visitatori dagli album riservati. Qui esce solo chi ha fatto
    l'accesso, e ne esce ovunque — compreso il dispositivo da cui si sta
    premendo il pulsante, che e' l'unico comportamento onesto.
    """
    _check_csrf(user, csrf_token)
    dimentica_dispositivi(user["id"])
    log_event("INFO", "auth",
              f"Dispositivi ricordati sganciati per {user['username']}")
    return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
