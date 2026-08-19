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
    create_session, login_limiter, verify_csrf, _fidati_dal,
)
from ..templating import templates

router = APIRouter()

PENDING_COOKIE = "pc_2fa_pending"
PENDING_MAX_AGE = 300  # 5 minuti per inserire il codice
# Il dispositivo che si e' gia' fatto riconoscere una volta. Non da' accesso
# a niente da solo: dice soltanto "il codice a sei cifre qui l'hai gia'
# inserito", e serve a non doverlo ripescare dall'app ogni volta dal telefono
# di casa. Senza la password non apre nulla.
FIDATO_COOKIE = "pc_dispositivo"


def _pending_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().secret_key, salt="2fa-pending")


def _fidato_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().secret_key, salt="dispositivo")


def _set_session_cookie(response, token: str, lungo: bool = False):
    settings = get_settings()
    durata = (settings.session_max_age_lungo if lungo
              else settings.session_max_age)
    response.set_cookie(
        key=SESSION_COOKIE, value=token, max_age=durata,
        httponly=True, samesite="lax", secure=True, path="/",
    )
    return response


def _ricorda_dispositivo(response, user_id: int):
    """Segna questo dispositivo come gia' verificato, per il secondo
    passaggio. Vale quanto la sessione lunga e si sgancia dallo stesso
    pulsante."""
    response.set_cookie(
        key=FIDATO_COOKIE, value=_fidato_serializer().dumps({"uid": user_id}),
        max_age=get_settings().session_max_age_lungo,
        httponly=True, samesite="lax", secure=True, path="/",
    )
    return response


def _dispositivo_gia_verificato(request, user_id: int) -> bool:
    biscotto = request.cookies.get(FIDATO_COOKIE)
    if not biscotto:
        return False
    try:
        dati, emesso = _fidato_serializer().loads(
            biscotto, max_age=get_settings().session_max_age_lungo,
            return_timestamp=True)
    except Exception:
        return False
    if int(dati.get("uid", 0)) != int(user_id):
        return False
    # Lo stesso interruttore che sgancia le sessioni lunghe sgancia anche i
    # dispositivi: un pulsante solo, e vale per tutto.
    return emesso.timestamp() >= _fidati_dal(user_id)


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
def login_submit(request: Request, username: str = Form(...),
                 password: str = Form(...), ricorda: str = Form("0")):
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

    resta = ricorda == "1"

    if needs_2fa and not _dispositivo_gia_verificato(request, user_id):
        log_event("INFO", "auth", f"Password ok per '{username}', richiesto 2FA da {ip}")
        # La spunta viaggia dentro il biglietto firmato del passaggio
        # intermedio: cosi' non si perde fra il primo e il secondo modulo, e
        # non e' qualcosa che si possa aggiungere a mano dal browser.
        pending = _pending_serializer().dumps({"uid": user_id, "ricorda": resta})
        response = templates.TemplateResponse(request, "admin/login_2fa.html", {"error": None, "settings": settings},
        )
        response.set_cookie(key=PENDING_COOKIE, value=pending, max_age=PENDING_MAX_AGE,
                            httponly=True, samesite="lax", secure=True, path="/")
        return response

    if needs_2fa:
        log_event("INFO", "auth",
                  f"Login per '{username}' da {ip}: dispositivo gia' verificato")
    else:
        log_event("INFO", "auth", f"Login riuscito per '{username}' da {ip}")
    response = RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
    _set_session_cookie(response, create_session(user_id, lungo=resta), lungo=resta)
    if resta and needs_2fa:
        _ricorda_dispositivo(response, user_id)
    return response


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
        resta = bool(data.get("ricorda"))
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
    _set_session_cookie(response, create_session(user_id, lungo=resta), lungo=resta)
    if resta:
        _ricorda_dispositivo(response, user_id)
    return response


@router.post("/admin/logout")
def logout(request: Request, csrf_token: str = Form(...)):
    user = get_current_user(request)
    if user and not verify_csrf(user.get("csrf", ""), csrf_token):
        return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
    response = RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(PENDING_COOKIE, path="/")
    # Chi esce di proposito da un dispositivo se lo toglie anche dai
    # ricordati: altrimenti "esci" lascerebbe indietro il pezzo che salta
    # la verifica in due passaggi, che e' proprio quello che conta.
    response.delete_cookie(FIDATO_COOKIE, path="/")
    return response
