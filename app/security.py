"""Funzioni di sicurezza: hashing password, sessioni firmate, CSRF, rate limit.

- Password: Argon2id (resistente a brute-force e GPU cracking).
- Sessioni: cookie firmato con itsdangerous (HttpOnly, SameSite=Lax).
- CSRF: token sincronizzato legato alla sessione.
- Rate limit: semplice contatore in memoria per IP, adatto a un container
  single-instance. Per multi-worker si sposterebbe su SQLite/Redis.
"""
import hmac
import secrets
import time
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from .config import get_settings

_ph = PasswordHasher()


# ---------------- Password ----------------
def hash_password(password: str) -> str:
    """Restituisce l'hash Argon2id della password."""
    return _ph.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    """Verifica la password contro l'hash. False se non combacia."""
    try:
        return _ph.verify(hashed, password)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def needs_rehash(hashed: str) -> bool:
    """True se l'hash usa parametri obsoleti e va rigenerato."""
    try:
        return _ph.check_needs_rehash(hashed)
    except Exception:
        return False


# ---------------- Sessioni ----------------
def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().secret_key, salt="session")


def create_session(user_id: int) -> str:
    """Crea un cookie di sessione firmato contenente user_id e csrf token."""
    payload = {"uid": user_id, "csrf": secrets.token_urlsafe(24)}
    return _serializer().dumps(payload)


def read_session(token: Optional[str]) -> Optional[dict]:
    """Valida e decodifica il cookie di sessione. None se non valido/scaduto."""
    if not token:
        return None
    try:
        return _serializer().loads(token, max_age=get_settings().session_max_age)
    except (BadSignature, SignatureExpired):
        return None


# ---------------- CSRF ----------------
def verify_csrf(session_csrf: str, submitted: Optional[str]) -> bool:
    """Confronto costante-tempo del token CSRF."""
    if not session_csrf or not submitted:
        return False
    return hmac.compare_digest(session_csrf, submitted)


# ---------------- Album privati ----------------
def generate_access_token() -> str:
    """Token URL non indovinabile per album privati."""
    return secrets.token_urlsafe(16)


# ---------------- Rate limiting (in-memory) ----------------
class RateLimiter:
    """Rate limiter a finestra scorrevole, per chiave (es. IP).

    Semplice e senza dipendenze. Adatto a un'istanza singola. I dati
    stanno in RAM e si azzerano al riavvio: accettabile per la protezione
    brute-force del login.
    """
    def __init__(self, max_attempts: int, window_seconds: int = 300):
        self.max_attempts = max_attempts
        self.window = window_seconds
        self._hits: dict[str, list[float]] = {}

    def check(self, key: str) -> bool:
        """True se la richiesta e consentita, False se supera il limite."""
        now = time.time()
        hits = [t for t in self._hits.get(key, []) if now - t < self.window]
        self._hits[key] = hits
        if len(hits) >= self.max_attempts:
            return False
        return True

    def hit(self, key: str) -> None:
        """Registra un tentativo per la chiave."""
        self._hits.setdefault(key, []).append(time.time())

    def reset(self, key: str) -> None:
        """Azzera i tentativi (es. dopo login riuscito)."""
        self._hits.pop(key, None)


login_limiter = RateLimiter(max_attempts=get_settings().rate_limit_login, window_seconds=300)


# ---------------- Security headers ----------------
def security_headers() -> dict[str, str]:
    """Headers di sicurezza applicati a ogni risposta via middleware.

    Qui resta solo la Content-Security-Policy, perche' dipende da cosa
    contengono le pagine dell'applicazione. Gli altri (nosniff,
    X-Frame-Options, Referrer-Policy, Permissions-Policy, HSTS) li mette
    nginx, in snippets/photocarcifo-sicurezza.conf.

    Prima stavano in tutti e due i posti e arrivavano al browser due volte,
    con X-Frame-Options perfino in disaccordo con se stesso: DENY da qui,
    SAMEORIGIN da nginx. Un valore solo, scritto in un posto solo.

    CSP restrittiva: risorse solo dallo stesso origin, niente inline script
    (il JS e in file statici). 'unsafe-inline' resta solo per gli stili per
    compatibilita con eventuali attributi style minimi.
    """
    return {
        "Content-Security-Policy": (
            "default-src 'self'; "
            "img-src 'self' data:; "
            "style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        ),
    }
