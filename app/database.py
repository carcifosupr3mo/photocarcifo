"""Gestione database SQLite - modello ad ALBERO.

Il DB e un indice della struttura di cartelle del Synology. Rispecchia
l'albero reale: ogni cartella e un "nodo" con un genitore (parent_id),
e ogni foto/video e un "media" agganciato al nodo che lo contiene.
"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id     INTEGER,
    slug          TEXT    NOT NULL UNIQUE,
    rel_path      TEXT    NOT NULL UNIQUE,
    name          TEXT    NOT NULL,
    title         TEXT    NOT NULL,
    depth         INTEGER NOT NULL DEFAULT 0,
    description   TEXT    DEFAULT '',
    cover_media_id INTEGER,
    is_private    INTEGER NOT NULL DEFAULT 0,
    hidden        INTEGER NOT NULL DEFAULT 0,
    access_token  TEXT,
    password_hash TEXT,
    downloads_enabled INTEGER NOT NULL DEFAULT 1,
    sort_order    INTEGER NOT NULL DEFAULT 0,
    direct_media  INTEGER NOT NULL DEFAULT 0,
    total_media   INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL,
    updated_at    TEXT    NOT NULL,
    expires_at    TEXT,
    -- Data dello scatto piu' recente contenuto nella cartella o nelle sue
    -- sottocartelle. Si calcola nella scansione e non a ogni visita: e' il
    -- criterio con cui la home ordina gli album, e ricavarlo ogni volta
    -- costava 60 ms su ogni pagina.
    data_foto     REAL,
    FOREIGN KEY (parent_id) REFERENCES nodes(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS media (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id       INTEGER NOT NULL,
    kind          TEXT    NOT NULL DEFAULT 'image',
    rel_path      TEXT    NOT NULL UNIQUE,
    filename      TEXT    NOT NULL,
    width         INTEGER DEFAULT 0,
    height        INTEGER DEFAULT 0,
    duration      REAL    DEFAULT 0,
    size_bytes    INTEGER DEFAULT 0,
    mtime         REAL    NOT NULL,
    sort_order    INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL,
    ocr_stato     TEXT    NOT NULL DEFAULT '',
    ocr_at        TEXT,
    FOREIGN KEY (node_id) REFERENCES nodes(id) ON DELETE CASCADE
);

-- Numeri di gara letti sulle tabelle degli atleti. Una foto puo' contenere
-- piu' piloti, quindi piu' numeri; lo stesso numero compare una volta sola
-- per foto (vincolo UNIQUE).
CREATE TABLE IF NOT EXISTS media_numeri (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    media_id   INTEGER NOT NULL,
    numero     TEXT    NOT NULL,           -- normalizzato, senza zeri davanti
    origine    TEXT    NOT NULL DEFAULT 'ocr',   -- ocr | manuale
    confidenza REAL    NOT NULL DEFAULT 0,
    -- Dove si trovava il numero nell'inquadratura (0-1). Serve a capire se
    -- e' una tabella che si muove o un cartello fisso dell'impianto.
    pos_x      REAL,
    pos_y      REAL,
    altezza    REAL,
    created_at TEXT    NOT NULL,
    UNIQUE(media_id, numero),
    FOREIGN KEY (media_id) REFERENCES media(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    is_admin      INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT    NOT NULL,
    totp_secret   TEXT,
    totp_enabled  INTEGER NOT NULL DEFAULT 0
);

-- Fotografie che un visitatore ha segnato come preferite. L'identificativo
-- "ospite" e' casuale e vive nel cookie del browser: nessuna registrazione.
CREATE TABLE IF NOT EXISTS preferiti (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ospite    TEXT    NOT NULL,
    media_id  INTEGER NOT NULL,
    node_id   INTEGER NOT NULL,
    ts        TEXT    NOT NULL,
    instagram TEXT,
    UNIQUE(ospite, media_id)
);

CREATE TABLE IF NOT EXISTS raduni (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    data   TEXT NOT NULL,
    ora    TEXT,
    luogo  TEXT NOT NULL,
    note   TEXT,
    creato TEXT,
    mappa  TEXT
);

CREATE TABLE IF NOT EXISTS recensioni (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    nome         TEXT    NOT NULL,
    voto         INTEGER NOT NULL,
    testo        TEXT    NOT NULL,
    evento       TEXT    NOT NULL DEFAULT '',
    lingua       TEXT    NOT NULL DEFAULT 'it',
    creato_at    TEXT    NOT NULL,
    approvata    INTEGER NOT NULL DEFAULT 0,
    ip           TEXT    NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    level      TEXT NOT NULL,
    category   TEXT NOT NULL,
    message    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stats (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    event      TEXT NOT NULL,
    ref        TEXT
);

-- Che cosa cerca la gente nel sito, e se lo ha trovato.
--
-- Le ricerche che non danno risultati sono l'unica voce dei visitatori che
-- arriva fin qui: non essendoci moduli di contatto, nessuno puo' dire "la
-- mia gara non c'e'" o "il mio numero non lo trova". Una riga per testo
-- cercato, con un contatore: cosi' "1 volta per sbaglio" e "quaranta volte
-- in un mese" si distinguono a colpo d'occhio.
--
-- Non si registra ne' l'indirizzo di chi cerca ne' altro che lo identifichi:
-- resta solo la parola cercata.
-- Tentativi falliti di indovinare una password: quella del pannello e
-- quella dei raduni.
--
-- Stavano nella memoria del processo web. Finche' il processo era uno solo
-- funzionava; con piu' processi in parallelo ognuno avrebbe tenuto il
-- proprio conto, e chi prova a indovinare avrebbe avuto il limite
-- moltiplicato per il numero di processi solo perche' le sue richieste si
-- distribuiscono fra loro. Qui il conto e' uno e lo vedono tutti.
--
-- In piu' non si azzerano piu' a ogni riavvio del sito: prima bastava che
-- il servizio ripartisse, cosa che succede ogni notte.
CREATE TABLE IF NOT EXISTS tentativi (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ambito  TEXT NOT NULL,          -- 'login' | 'raduni'
    chiave  TEXT NOT NULL,          -- indirizzo di chi ha provato
    quando  REAL NOT NULL           -- momento del tentativo
);

CREATE TABLE IF NOT EXISTS ricerche (
    testo      TEXT    PRIMARY KEY,          -- normalizzato: minuscolo, spazi singoli
    numero     TEXT,                         -- numero di gara riconosciuto, se c'era
    risultati  INTEGER NOT NULL DEFAULT 0,   -- quanti ne ha trovati l'ultima volta
    volte      INTEGER NOT NULL DEFAULT 0,
    primo_at   TEXT    NOT NULL,
    ultimo_at  TEXT    NOT NULL
);

"""

# Colonne aggiunte dopo la prima versione. Sui database gia' esistenti il
# CREATE TABLE IF NOT EXISTS non ha alcun effetto, quindi vanno aggiunte
# qui: senza, aggiornare il codice romperebbe il sito.
MIGRAZIONI: list[tuple[str, str, str]] = [
    # (tabella, colonna, definizione)
    ("nodes", "hidden", "INTEGER NOT NULL DEFAULT 0"),
    ("nodes", "expires_at", "TEXT"),
    ("users", "totp_secret", "TEXT"),
    ("users", "totp_enabled", "INTEGER NOT NULL DEFAULT 0"),
    ("preferiti", "instagram", "TEXT"),
    ("raduni", "mappa", "TEXT"),
    ("media", "ocr_stato", "TEXT NOT NULL DEFAULT ''"),
    ("media", "ocr_at", "TEXT"),
    ("media_numeri", "pos_x", "REAL"),
    ("media_numeri", "pos_y", "REAL"),
    ("media_numeri", "altezza", "REAL"),
    ("nodes", "data_foto", "REAL"),
]

# Gli indici stanno a parte perche' vanno creati DOPO le migrazioni: alcuni
# riguardano colonne che solo la migrazione ha appena aggiunto.
INDICI = """
CREATE INDEX IF NOT EXISTS idx_nodes_parent  ON nodes(parent_id);
CREATE INDEX IF NOT EXISTS idx_nodes_private ON nodes(is_private);
CREATE INDEX IF NOT EXISTS idx_nodes_token   ON nodes(access_token);
CREATE INDEX IF NOT EXISTS idx_media_node    ON media(node_id);
CREATE INDEX IF NOT EXISTS idx_media_kind    ON media(kind);
CREATE INDEX IF NOT EXISTS idx_media_ocr     ON media(ocr_stato);
CREATE INDEX IF NOT EXISTS idx_stats_event   ON stats(event);
CREATE INDEX IF NOT EXISTS idx_numeri_numero ON media_numeri(numero);
CREATE INDEX IF NOT EXISTS idx_numeri_media  ON media_numeri(media_id);
CREATE INDEX IF NOT EXISTS idx_pref_node     ON preferiti(node_id);
CREATE INDEX IF NOT EXISTS idx_pref_ospite   ON preferiti(ospite, node_id);
CREATE INDEX IF NOT EXISTS idx_raduni_data   ON raduni(data);
CREATE INDEX IF NOT EXISTS idx_nodes_data    ON nodes(data_foto);
CREATE INDEX IF NOT EXISTS idx_rec_pub      ON recensioni(approvata, creato_at);
CREATE INDEX IF NOT EXISTS idx_ricerche_vuote ON ricerche(risultati, volte);
CREATE INDEX IF NOT EXISTS idx_tentativi     ON tentativi(ambito, chiave, quando);
"""


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    settings = get_settings()
    conn = sqlite3.connect(str(settings.db_path), timeout=60.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    # In MILLISECONDI. Il valore precedente (60.00) veniva letto come 60
    # millisecondi e per di piu' annullava i 60 secondi passati a connect():
    # bastava una scrittura in corso altrove per far fallire la richiesta
    # con "database is locked".
    conn.execute("PRAGMA busy_timeout=60000;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    settings = get_settings()
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    with get_db() as conn:
        conn.executescript(SCHEMA)
        _applica_migrazioni(conn)
        conn.executescript(INDICI)


def _applica_migrazioni(conn: sqlite3.Connection) -> None:
    """Aggiunge le colonne mancanti ai database creati con versioni precedenti."""
    for tabella, colonna, definizione in MIGRAZIONI:
        presenti = {r["name"] for r in
                    conn.execute(f"PRAGMA table_info({tabella})").fetchall()}
        if not presenti:
            continue          # tabella non ancora creata: ci pensa lo SCHEMA
        if colonna in presenti:
            continue
        try:
            conn.execute(
                f"ALTER TABLE {tabella} ADD COLUMN {colonna} {definizione}")
        except sqlite3.OperationalError as errore:
            # Il sito, la scansione e la lettura dei numeri possono avviarsi
            # nello stesso momento e tentare la stessa migrazione: chi arriva
            # secondo trova la colonna gia' creata. Non e' un errore.
            if "duplicate column" not in str(errore).lower():
                raise


def sottoalbero_like(rel_path: str) -> str:
    """Pattern LIKE per prendere le sottocartelle di un percorso.

    I nomi delle cartelle contengono quasi sempre "_", che per SQL LIKE e'
    un jolly che sostituisce un carattere qualsiasi. Senza protezione,
    "Gara_Verona/%" prenderebbe anche "Gara-Verona/...": rendere privata una
    cartella ne renderebbe privata un'altra, e mandarne una nel cestino
    cancellerebbe dal database anche l'estranea.

    Va usato sempre insieme a ESCAPE '\\' nella query.
    """
    fuga = (rel_path.replace("\\", "\\\\")
                    .replace("%", "\\%")
                    .replace("_", "\\_"))
    return fuga + "/%"


def get_setting(key: str, default: str = "") -> str:
    with get_db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def log_event(level: str, category: str, message: str) -> None:
    from datetime import datetime, timezone
    with get_db() as conn:
        conn.execute(
            "INSERT INTO logs(ts, level, category, message) VALUES(?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(), level, category, message),
        )


def record_stat(event: str, ref: str = "") -> None:
    from datetime import datetime, timezone
    with get_db() as conn:
        conn.execute(
            "INSERT INTO stats(ts, event, ref) VALUES(?,?,?)",
            (datetime.now(timezone.utc).isoformat(), event, ref),
        )


# --- Statistiche accumulate ---
# Le visite vengono tenute in memoria e scritte a gruppi: con i programmi
# di scansione dei motori di ricerca si evitano migliaia di scritture.
_coda_stat = []
_MAX_CODA = 25


def record_stat_bufferizzato(event: str, ref: str = "") -> None:
    from datetime import datetime, timezone
    _coda_stat.append((datetime.now(timezone.utc).isoformat(), event, ref))
    if len(_coda_stat) >= _MAX_CODA:
        svuota_stat()


def svuota_stat() -> int:
    if not _coda_stat:
        return 0
    righe = list(_coda_stat)
    _coda_stat.clear()
    try:
        with get_db() as conn:
            conn.executemany(
                "INSERT INTO stats(ts, event, ref) VALUES(?,?,?)", righe)
        return len(righe)
    except Exception:
        return 0


# --- Ricerche dei visitatori ---
_MAX_RICERCA = 100


def normalizza_ricerca(testo: str) -> str:
    """Forma con cui la ricerca viene contata.

    "Bmx  RIAZZINO" e "bmx riazzino" sono la stessa domanda: senza ridurle
    alla stessa forma comparirebbero come due righe diverse, ognuna con il
    suo contatore a 1, e non si vedrebbe piu' quali sono le richieste
    davvero frequenti.
    """
    return " ".join(testo.lower().split())[:_MAX_RICERCA]


def registra_ricerca(testo: str, numero: str | None, risultati: int) -> None:
    """Annota che qualcuno ha cercato questo, e quanto ha trovato.

    Non deve mai far fallire la pagina di ricerca: se la scrittura non
    riesce (database occupato, disco pieno) il visitatore ha comunque i suoi
    risultati, ed e' l'unica cosa che gli interessa.
    """
    from datetime import datetime, timezone
    chiave = normalizza_ricerca(testo)
    if not chiave:
        return
    adesso = datetime.now(timezone.utc).isoformat()
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO ricerche(testo, numero, risultati, volte, "
                "                     primo_at, ultimo_at) "
                "VALUES(?,?,?,1,?,?) "
                "ON CONFLICT(testo) DO UPDATE SET "
                "  numero=excluded.numero, "
                "  risultati=excluded.risultati, "
                "  volte=volte+1, "
                "  ultimo_at=excluded.ultimo_at",
                (chiave, numero or None, int(risultati), adesso, adesso))
    except Exception:
        pass


def ricalcola_date_album(conn) -> None:
    """Aggiorna la data dello scatto piu' recente di ogni cartella.

    La home e le pagine degli album ordinano per questa data. Calcolarla al
    volo richiedeva una sottoquery su tutte le fotografie a ogni visita;
    salvandola si fa una volta sola, quando l'archivio cambia.

    Il confronto usa substr e non LIKE perche' i nomi delle cartelle
    contengono "_", che per LIKE e' un carattere jolly.
    """
    conn.execute(
        "UPDATE nodes SET data_foto = ("
        " SELECT MAX(m.mtime) FROM media m JOIN nodes n2 ON n2.id = m.node_id"
        " WHERE n2.rel_path = nodes.rel_path"
        " OR substr(n2.rel_path, 1, length(nodes.rel_path) + 1)"
        "    = nodes.rel_path || '/')")
