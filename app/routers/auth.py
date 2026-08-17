"""Router di autenticazione: login (con 2FA opzionale) e logout.

- Login con rate limit per IP (protezione brute-force).
- Password verificata con Argon2; rehash trasparente se obsoleto.
- Se l'utente ha il 2FA attivo, dopo la password serve il codice TOTP.
  Lo stato intermedio viaggia in un cookie firmato di breve durata,
  che non concede alcun accesso finche' il codice non e' verificato.
- Sessione in cookie firmato HttpOnly + SameSite=Lax; CSRF sul logout.
"""
import pyotp
from itsdangerous import URLSafeTimedSerializer, BadSignature

from fastapi import APIRouter, Request, Form, status
from fastapi.responses import HTMLResponse, RedirectResponse

from ..config import get_settings
from ..database import get_db, log_event
from ..deps import SESSION_COOKIE, client_ip, get_current_user
from ..security import (
    verify_password, needs_rehash, hash_password,
    create_session, login_limiter, verify_csrf,
)
from ..templating import templates

router = APIRouter()

PENDING_COOKIE = "pc_2fa_pending"
PENDING_MAX_AGE = 300  # 5 minuti per inserire il codice


def _pending_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().secret_key, salt="2fa-pending")


def _set_session_cookie(response, token: str):
    settings = get_settings()
    response.set_cookie(
        key=SESSION_COOKIE, value=token, max_age=settings.session_max_age,
        httponly=True, samesite="lax", secure=True, path="/",
    )
    return response


def _login_error(request, message, code=status.HTTP_401_UNAUTHORIZED):
    return templates.TemplateResponse(request, "admin/login.html", {"error": message, "settings": get_settings()},
        status_code=code,
    )


@router.get("/admin/login", response_class=HTMLResponse)
def login_page(request: Request):
    if get_current_user(request):
        return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(request, "admin/login.html", {"error": None, "settings": get_settings()},
    )


@router.post("/admin/login", response_class=HTMLResponse)
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    settings = get_settings()
    ip = client_ip(request)

    if not login_limiter.check(ip):
        log_event("WARNING", "auth", f"Rate limit login superato da {ip}")
        return _login_error(request, "Troppi tentativi. Riprova tra qualche minuto.",
                            status.HTTP_429_TOO_MANY_REQUESTS)

    with get_db() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash, totp_enabled FROM users WHERE username=?",
            (username,),
        ).fetchone()

        ok = bool(row) and verify_password(password, row["password_hash"])
        if not ok:
            login_limiter.hit(ip)
            log_event("WARNING", "auth", f"Login fallito per '{username}' da {ip}")
            return _login_error(request, "Credenziali non valide.")

        if needs_rehash(row["password_hash"]):
            conn.execute("UPDATE users SET password_hash=? WHERE id=?",
                         (hash_password(password), row["id"]))

        user_id = row["id"]
        needs_2fa = bool(row["totp_enabled"])

    login_limiter.reset(ip)

    if needs_2fa:
        log_event("INFO", "auth", f"Password ok per '{username}', richiesto 2FA da {ip}")
        pending = _pending_serializer().dumps({"uid": user_id})
        response = templates.TemplateResponse(request, "admin/login_2fa.html", {"error": None, "settings": settings},
        )
        response.set_cookie(key=PENDING_COOKIE, value=pending, max_age=PENDING_MAX_AGE,
                            httponly=True, samesite="lax", secure=True, path="/")
        return response

    log_event("INFO", "auth", f"Login riuscito per '{username}' da {ip}")
    response = RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
    return _set_session_cookie(response, create_session(user_id))


@router.post("/admin/login/2fa", response_class=HTMLResponse)
def login_2fa(request: Request, code: str = Form(...)):
    settings = get_settings()
    ip = client_ip(request)

    if not login_limiter.check(ip):
        return _login_error(request, "Troppi tentativi. Riprova tra qualche minuto.",
                            status.HTTP_429_TOO_MANY_REQUESTS)

    pending = request.cookies.get(PENDING_COOKIE)
    if not pending:
        return _login_error(request, "Sessione scaduta. Rifai il login.")
    try:
        data = _pending_serializer().loads(pending, max_age=PENDING_MAX_AGE)
        user_id = int(data["uid"])
    except (BadSignature, Exception):
        return _login_error(request, "Sessione scaduta. Rifai il login.")

    with get_db() as conn:
        row = conn.execute(
            "SELECT username, totp_secret, totp_enabled FROM users WHERE id=?",
            (user_id,)).fetchone()

    if not row or not row["totp_enabled"] or not row["totp_secret"]:
        return _login_error(request, "Verifica non disponibile. Rifai il login.")

    if not pyotp.TOTP(row["totp_secret"]).verify(code.strip(), valid_window=1):
        login_limiter.hit(ip)
        log_event("WARNING", "auth", f"Codice 2FA errato per '{row['username']}' da {ip}")
        return templates.TemplateResponse(request, "admin/login_2fa.html", {"error": "Codice non valido.", "settings": settings},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    login_limiter.reset(ip)
    log_event("INFO", "auth", f"Login 2FA riuscito per '{row['username']}' da {ip}")
    response = RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(PENDING_COOKIE, path="/")
    return _set_session_cookie(response, create_session(user_id))


@router.post("/admin/logout")
def logout(request: Request, csrf_token: str = Form(...)):
    user = get_current_user(request)
    if user and not verify_csrf(user.get("csrf", ""), csrf_token):
        return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
    response = RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(PENDING_COOKIE, path="/")
    return response
