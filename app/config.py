"""Configurazione centralizzata dell'applicazione.

Tutte le impostazioni provengono da variabili d'ambiente (.env), cosi da
non avere segreti hard-coded nel codice sorgente. Usa pydantic-settings
per validazione e tipizzazione automatica.
"""
from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Sicurezza
    secret_key: str
    session_max_age: int = 86400          # durata sessione in secondi
    # Quanto dura la sessione di chi ha spuntato "resta collegato su
    # questo dispositivo". Novanta giorni: abbastanza da non rifare mai
    # il login dal telefono, poco abbastanza da non essere per sempre.
    session_max_age_lungo: int = 7776000  # 90 giorni
    # Tentativi di login/2FA per finestra di 5 minuti (vedi security.py,
    # login_limiter/totp_limiter). Alzato da 5 a 50 il 01/09/2026, richiesto
    # esplicitamente: un utente vero che sbaglia la password/il codice
    # TOTP qualche volta non deve restare bloccato, mentre chi tenta
    # centinaia di combinazioni al minuto resta comunque fermato — la
    # protezione vera contro il bruteforce e' Argon2id (lento di proposito)
    # piu' il limite di 8 richieste/minuto per IP gia' imposto da nginx
    # (zona pclogin), non questo contatore da solo.
    rate_limit_login: int = 50

    # Chiave IndexNow (vedi app/indexnow.py). Non e' un segreto nel senso
    # classico: lo standard la vuole leggibile pubblicamente all'indirizzo
    # https://photocarcifo.ch/<chiave>.txt, per questo vive qui insieme al
    # resto della configurazione invece che in un posto protetto a parte.
    # Stringa esadecimale di 32 caratteri, il formato che IndexNow richiede
    # (solo lettere a-f e cifre); vuota = IndexNow disattivato, nessuna
    # notifica viene tentata.
    indexnow_key: str = ""

    # Percorsi
    photo_root: str = "/mnt/magazzino"    # mount SMB del Synology (read-only)
    data_dir: str = "/opt/photocarcifo/data"

    # Identita sito
    site_name: str = "Photocarcifo"
    site_url: str = "http://192.168.1.206"

    # Credenziali admin iniziali (usate solo al primo avvio per il seed)
    admin_username: str = "admin"
    admin_password: str = "changeme"

    # Thumbnail
    thumb_small: int = 400                # lato lungo miniatura griglia
    thumb_medium: int = 1200              # lato lungo per viewer
    thumb_quality: int = 82

    # Sincronizzazione
    scan_interval_minutes: int = 10

    # Serving immagini: se true delega a Nginx via X-Accel-Redirect
    use_xaccel: bool = True

    # --- Lettura automatica dei numeri di gara sulle tabelle ---
    ocr_enabled: bool = True
    # Lato lungo in px a cui viene ridotta la foto per l'analisi. 1800 e' la
    # stessa misura delle miniature grandi gia' in cache: cosi' il risultato
    # e' identico sia partendo dalla miniatura sia dall'originale. Alzarlo
    # trova qualche tabella lontana in piu', ma rallenta.
    ocr_max_side: int = 1800
    # Sicurezza minima della lettura (0-1). Tarata sulle foto vere: sotto
    # 0.95 le letture sono quasi tutte sbagliate (un 377 letto come 371,
    # numeri inventati su foto di premiazione, cifre pescate dalle scritte
    # delle maglie), sopra 0.95 sono affidabili. Un numero sbagliato fa
    # doppio danno: sporca la ricerca di un pilota e nasconde quella di un
    # altro.
    ocr_min_confidence: float = 0.95
    # Altezza minima del numero rispetto alla foto. Deve restare bassa: nelle
    # foto d'azione i piloti lontani hanno tabelle alte l'1% dell'immagine, e
    # una soglia alta le butterebbe via tutte. A separare le tabelle dalle
    # scritte di sponsor e striscioni ci pensa il filtro "solo cifre".
    ocr_min_height_ratio: float = 0.008
    ocr_max_digits: int = 4           # numeri piu' lunghi vengono ignorati
    # Cifre minime perche' una lettura valga come numero di gara. Vale 1
    # perche' le tabelle da 1 a 9 esistono e devono essere trovate.
    ocr_min_digits: int = 1
    # Cartelle dove le cifre singole vengono ignorate. Nell'atletica sono i
    # numeri di corsia stampati sui blocchi di partenza: grandi, nitidi e
    # letti con sicurezza altissima (0.98-1.00), quindi nessuna soglia li
    # distingue da una tabella. Li' i pettorali sono comunque a tre cifre,
    # percio' non si perde nulla. Elenco separato da virgole.
    ocr_niente_cifre_singole: str = "ATLETICA"
    ocr_batch_size: int = 4000        # foto per esecuzione del timer di sistema
    # Cartella da leggere per prima. La ricerca per numero serve soprattutto
    # alle gare con le tabelle, quindi si parte da li' invece di seguire
    # l'ordine dell'archivio. Dentro ogni gruppo si comincia dalle foto piu'
    # recenti, che sono quelle che la gente cerca appena finita la gara.
    # Vuoto = nessuna priorita'.
    ocr_priorita: str = "BMX"
    ocr_workers: int = 0              # processi in parallelo; 0 = decide da solo
    # Memoria occupata da ogni processo di lettura. Misurata sul campo: i
    # modelli piu' i buffer delle immagini grandi stanno intorno ai 520 MB.
    ocr_mb_per_worker: int = 550

    # --- Percorsi derivati (proprieta comode, non campi env) ---
    @property
    def data_path(self) -> Path:
        return Path(self.data_dir)

    @property
    def db_path(self) -> Path:
        return self.data_path / "photocarcifo.db"

    @property
    def thumb_cache_path(self) -> Path:
        return self.data_path / "cache" / "thumbnails"

    @property
    def logs_path(self) -> Path:
        return self.data_path / "logs"

    @property
    def photo_root_path(self) -> Path:
        return Path(self.photo_root)

    def ensure_dirs(self) -> None:
        """Crea le cartelle dati locali se non esistono."""
        self.thumb_cache_path.mkdir(parents=True, exist_ok=True)
        self.logs_path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    """Istanza singleton delle impostazioni (cache in memoria)."""
    s = Settings()
    s.ensure_dirs()
    return s
