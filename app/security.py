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


# ---------------- Conteggio dei tentativi ----------------
class RateLimiter:
    """Conta i tentativi falliti per chiave (di norma l'indirizzo di rete).

    I tentativi si scrivono nel database e non nella memoria del processo.
    E' l'unica forma che regge quando il sito gira su piu' processi in
    parallelo: con il conteggio in memoria, ognuno terrebbe il proprio, e
    chi prova a indovinare la password avrebbe a disposizione il limite
    moltiplicato per il numero di processi — con quattro processi, quaranta
    tentativi invece di dieci, semplicemente perche' le richieste si
    distribuiscono. Il database e' l'unico posto che tutti vedono.

    Ha anche un effetto collaterale utile: i tentativi non si azzerano piu'
    al riavvio del sito. Prima bastava che il servizio ripartisse — cosa
    che succede ogni notte — per ripulire la lavagna a chi stava provando.

    La finestra e' scorrevole: contano solo i tentativi degli ultimi
    `window_seconds` secondi, non quelli di ore prima.
    """

    def __init__(self, ambito: str, max_attempts: int, window_seconds: int = 300):
        self.ambito = ambito
        self.max_attempts = max_attempts
        self.window = window_seconds

    def _conta(self, conn, key: str) -> int:
        return conn.execute(
            "SELECT COUNT(*) c FROM tentativi WHERE ambito=? AND chiave=? "
            "AND quando > ?",
            (self.ambito, key, time.time() - self.window)).fetchone()["c"]

    def check(self, key: str) -> bool:
        """Vero se il tentativo e' consentito, falso se ha gia' esagerato."""
        from .database import get_db
        try:
            with get_db() as conn:
                return self._conta(conn, key) < self.max_attempts
        except Exception:
            # Se il database non risponde non si chiude fuori nessuno: il
            # sito e' gia' in avaria per conto suo, e trasformare un guasto
            # di lettura in "non puoi entrare" non aiuta.
            return True

    def hit(self, key: str) -> None:
        """Registra un tentativo fallito."""
        from .database import get_db
        try:
            with get_db() as conn:
                conn.execute(
                    "INSERT INTO tentativi (ambito, chiave, quando) VALUES (?,?,?)",
                    (self.ambito, key, time.time()))
                # Pulizia opportunistica: le righe vecchie non servono a
                # nessuno e sarebbe uno spreco avere un lavoro apposta.
                conn.execute(
                    "DELETE FROM tentativi WHERE quando < ?",
                    (time.time() - max(self.window, 3600) * 24,))
        except Exception:
            pass

    def resta(self, key: str) -> int:
        """Quanti tentativi mancano al blocco. Serve solo a spiegarlo a chi
        sta sbagliando, e a scriverlo nei registri."""
        from .database import get_db
        try:
            with get_db() as conn:
                return max(0, self.max_attempts - self._conta(conn, key))
        except Exception:
            return self.max_attempts

    def reset(self, key: str) -> None:
        """Azzera i tentativi, per esempio dopo un accesso riuscito."""
        from .database import get_db
        try:
            with get_db() as conn:
                conn.execute("DELETE FROM tentativi WHERE ambito=? AND chiave=?",
                             (self.ambito, key))
        except Exception:
            pass


login_limiter = RateLimiter("login", max_attempts=get_settings().rate_limit_login,
                            window_seconds=300)


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
