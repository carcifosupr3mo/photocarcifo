"""Attrezzatura comune ai test.

I test girano contro l'applicazione vera, con un database ISOLATO: una
copia del database reale, presa e sanificata una volta sola all'avvio
della sessione, mai il file di produzione. Sono controlli di
funzionamento, non di laboratorio: verificano che il sito risponda come
deve con dati che hanno la stessa forma di quelli veri (stessi album,
stesse relazioni, stessi conteggi), senza che un solo byte del sito vero
possa mai essere letto o scritto durante la suite.

Si lanciano cosi', dalla cartella del sito:

    venv/bin/python -m pytest tests -q

Isolamento dal database di produzione (aggiunto 08/09/2026)
-------------------------------------------------------------------------
Fino a questa data la frase sopra era una convenzione, non una barriera:
nessuna fixture impediva a un test di scrivere per davvero. Un audit di
sicurezza ha trovato una condivisione vera, funzionante, lasciata nel
database di produzione da client.post("/condividi/selezione") - e lo
stesso identico problema esisteva in test_contattami.py, che scrive
righe vere in richieste_contatto (nome, email, telefono di un mittente
reale) e le ripulisce a mano, sperando che nessun test fallisca a meta'
prima di arrivare alla riga che le cancella.

Le righe qui sotto, PRIMA di qualunque altra cosa nel file, risolvono la
causa e non il singolo sintomo:

1. Si prende un'istantanea del database vero (sqlite3 Connection.backup,
   coerente anche con WAL attivo) in un file temporaneo a parte.
2. Nella COPIA - mai nell'originale - si cancella ogni token, password,
   nome e indirizzo IP reali: nessun segreto e nessun dato personale di
   produzione resta leggibile durante i test, nemmeno per la durata della
   sessione.
3. La variabile d'ambiente DATA_DIR viene fatta puntare alla cartella
   temporanea PRIMA che qualunque modulo dell'applicazione venga
   importato: get_settings() e' @lru_cache, e alcuni moduli (app.security)
   la interrogano gia' al momento di essere importati per costruire i
   limitatori di frequenza. conftest.py e' il primo file che pytest
   importa, prima di qualunque modulo di test: e' l'unico punto in cui si
   e' certi di arrivare prima di ogni import applicativo.
4. Come rete di sicurezza indipendente da tutto questo, sqlite3.connect
   viene sorvegliato per l'intera sessione: qualunque tentativo di
   collegarsi al file di produzione, da qualunque modulo o test, futuro o
   presente, fallisce subito con un errore chiaro invece di riuscire in
   silenzio. Si sorveglia la funzione di libreria - condivisa da tutto il
   processo, un solo "import sqlite3" per tutti - invece di inseguire
   ogni singolo "from ..database import get_db" sparso nei router: e'
   proprio un import di quel tipo, fatto in ritardo dentro una funzione,
   che aveva gia' aggirato un monkeypatch mirato a un solo modulo (vedi
   il fix precedente in tests/test_raduni.py).

Si copia il database vero invece di crearne uno vuoto con dati inventati
perche' gran parte della suite conta su relazioni e quantita' reali (un
album pubblico con foto, uno privato, uno nascosto, la gerarchia degli
album...): riscriverla da zero per una manciata di record finti avrebbe
richiesto di rimettere mano a centinaia di test che oggi si aspettano
quella forma - molto piu' rischioso del problema che si vuole risolvere.
"""
import hashlib
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE))

# --- 0. Impronta del database vero, presa con una lettura di file pura -----
# Niente sqlite3.connect qui: e' la prova che si porta a fine sessione per
# dimostrare che il file di produzione non e' stato toccato, ed e' presa
# PRIMA di installare la guardia qualche riga piu' sotto - dopo, anche
# questa stessa funzione sarebbe bloccata se usasse sqlite3.
DB_PRODUZIONE = (RADICE / "data" / "photocarcifo.db").resolve()


def impronta_file(percorso: Path):
    """sha256 dei byte del file, o None se non esiste (ambiente senza
    dati veri, es. un clone appena fatto: init_db() creera' lo schema
    vuoto e la sessione di test procede comunque)."""
    try:
        return hashlib.sha256(percorso.read_bytes()).hexdigest()
    except OSError:
        return None


IMPRONTA_PRODUZIONE_INIZIALE = impronta_file(DB_PRODUZIONE)

# --- 1. Copia isolata, sanificata, in una cartella temporanea --------------
CARTELLA_TEST = Path(tempfile.mkdtemp(prefix="photocarcifo-test-db-"))
DB_TEST = CARTELLA_TEST / "photocarcifo.db"


def _sanifica(conn: sqlite3.Connection) -> None:
    """Cancella dalla COPIA ogni token, password e dato personale reale.

    I valori rigenerati non devono combaciare con niente di esterno: la
    sessione di test li crea, li legge e li usa tutti da sola. randomblob
    basta a evitare collisioni sulle colonne UNIQUE (access_token,
    share_token, condivisioni.token) per le poche centinaia di righe che
    li usano davvero.
    """
    from argon2 import PasswordHasher
    hash_finto = PasswordHasher().hash("password-di-test-mai-valida-altrove")

    conn.executescript("""
        UPDATE nodes SET access_token = lower(hex(randomblob(16)))
            WHERE access_token IS NOT NULL;
        UPDATE nodes SET password_hash = NULL
            WHERE password_hash IS NOT NULL;
        UPDATE media SET share_token = lower(hex(randomblob(16))),
                         share_expires_at = NULL
            WHERE share_token IS NOT NULL;
        UPDATE condivisioni SET token = lower(hex(randomblob(16)));
        UPDATE richieste_contatto SET
            nome='Test', cognome='Test', email='test@example.invalid',
            telefono='', messaggio='(dato sanificato per i test)', ip='';
        UPDATE recensioni SET nome='Test', ip='';
        UPDATE tentativi SET chiave='0.0.0.0';
        DELETE FROM logs;
    """)
    conn.execute("UPDATE users SET password_hash=?, totp_secret=NULL, "
                "totp_enabled=0", (hash_finto,))
    conn.commit()


def _copia_e_sanifica_db_test() -> None:
    if not DB_PRODUZIONE.exists():
        return  # niente da copiare: init_db() piu' sotto crea uno schema vuoto
    sorgente = sqlite3.connect(f"file:{DB_PRODUZIONE}?mode=ro", uri=True)
    destinazione = sqlite3.connect(str(DB_TEST))
    try:
        sorgente.backup(destinazione)  # coerente anche con WAL attivo
    finally:
        sorgente.close()
    try:
        _sanifica(destinazione)
    finally:
        destinazione.close()


_copia_e_sanifica_db_test()

# --- 2. Il database di produzione, per get_settings(), da qui non esiste
# piu': ogni modulo che chiede la cartella dati riceve quella temporanea.
# Deve avvenire PRIMA di qualunque "import app...." nel resto del file (e
# infatti e' qui, non dentro una fixture: una fixture gira solo quando
# viene richiesta, un modulo si importa una volta sola e prima di tutto).
os.environ["DATA_DIR"] = str(CARTELLA_TEST)
os.environ["SECRET_KEY"] = "chiave-di-sessione-di-test-mai-usata-altrove"


def pytest_sessionfinish(session, exitstatus):
    """Fine della sessione: la cartella temporanea sparisce con lei, non
    resta mai un file tipo data/test.db dimenticato in giro."""
    shutil.rmtree(CARTELLA_TEST, ignore_errors=True)


# --- 3. Guardia fail-closed: nessuna connessione al file vero, mai -------
_connect_reale = sqlite3.connect
_DB_PRODUZIONE_STR = str(DB_PRODUZIONE)


def _connect_sorvegliato(database, *args, **kwargs):
    percorso = str(database)
    try:
        risolto = str(Path(percorso).resolve())
    except (OSError, ValueError, RuntimeError):
        risolto = percorso
    if percorso == _DB_PRODUZIONE_STR or risolto == _DB_PRODUZIONE_STR:
        raise RuntimeError(
            "BLOCCATO: un test ha provato a collegarsi al database di "
            f"produzione ({_DB_PRODUZIONE_STR}) invece che a quello "
            "isolato di test. Nessuna connessione e' stata aperta - "
            "vedi tests/conftest.py."
        )
    return _connect_reale(database, *args, **kwargs)


sqlite3.connect = _connect_sorvegliato


@pytest.fixture(autouse=True)
def telegram_finto(monkeypatch):
    """Nessun test manda mai un messaggio Telegram vero.

    Fino al 26/08/2026 i test del modulo di contatto (tests/test_contattami.py)
    passavano davvero da app.telegram_avvisi.invia() ogni volta che un POST
    a /contattami arrivava fino all'insert: la funzione legge le credenziali
    vere da /etc/photocarcifo-telegram.conf (stesso bot amministrativo usato
    in produzione) e chiama davvero l'API di Telegram. Ogni run della suite
    mandava percio' notifiche reali nella chat vera.

    Questa fixture sostituisce invia() con un finto che non fa mai una
    richiesta di rete, per TUTTI i test (autouse), senza che il codice di
    produzione sappia di essere sotto test: nessun `if pytest` in
    app/telegram_avvisi.py o app/routers/contattami.py, la sostituzione
    avviene solo qui, lato test. Il fake registra ogni chiamata (testo
    ricevuto) in TELEGRAM_CHIAMATE, cosi' un test puo' comunque verificare
    che la notifica sarebbe partita e con quale contenuto, senza che parta
    per davvero. Un singolo test puo' comunque monkeypatchare di nuovo
    telegram_avvisi.invia per esercitare il percorso reale della funzione
    (es. verificare cosa succede con la config assente): monkeypatch non
    interferisce, l'override piu' specifico vince per la durata di quel
    test.
    """
    from app import telegram_avvisi
    chiamate = []

    def finto(testo, percorso_config=None):
        chiamate.append(testo)
        return True

    monkeypatch.setattr(telegram_avvisi, "invia", finto)
    yield chiamate


@pytest.fixture(scope="session")
def app():
    from app.main import app as applicazione
    return applicazione


@pytest.fixture(scope="session")
def client(app):
    # raise_server_exceptions=False: un errore dentro una pagina deve
    # arrivare al test come risposta 500, che e' quello che vedrebbe un
    # visitatore, invece di far esplodere il test con la traccia dello
    # stack. Cosi' i test misurano il comportamento del sito, non quello
    # della libreria.
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture(scope="session")
def sessione_admin():
    """Cookie di una sessione da amministratore, per i test del pannello."""
    from app.security import create_session
    return {"pc_session": create_session(1)}


@pytest.fixture(scope="session")
def client_admin(app, sessione_admin):
    """Come client, ma con l'accesso gia' fatto.

    Il cookie sta sul client e non sulla singola richiesta: passarlo a ogni
    chiamata e' deprecato, perche' non e' chiaro se debba restare per le
    successive."""
    with TestClient(app, raise_server_exceptions=False,
                    cookies=sessione_admin) as c:
        yield c


@pytest.fixture(scope="session")
def dati():
    """Qualche identificativo preso dal database di test (copia sanificata
    del vero: stessa forma, stessi conteggi, nessun token/nome reale)."""
    from app.database import get_db
    with get_db() as conn:
        pubblico = conn.execute(
            "SELECT n.slug, n.id FROM nodes n WHERE n.is_private=0 AND n.hidden=0 "
            "AND n.total_media>0 LIMIT 1").fetchone()
        foto = conn.execute(
            "SELECT m.id FROM media m JOIN nodes n ON n.id=m.node_id "
            "WHERE n.is_private=0 AND n.hidden=0 AND m.kind='image' LIMIT 1").fetchone()
        privato = conn.execute(
            "SELECT slug, access_token FROM nodes "
            "WHERE is_private=1 AND access_token IS NOT NULL LIMIT 1").fetchone()
        nascosto = conn.execute(
            "SELECT slug FROM nodes WHERE hidden=1 LIMIT 1").fetchone()
        foto_privata = conn.execute(
            "SELECT m.id FROM media m JOIN nodes n ON n.id=m.node_id "
            "WHERE n.is_private=1 LIMIT 1").fetchone()
    return {
        "slug": pubblico["slug"] if pubblico else None,
        "node_id": pubblico["id"] if pubblico else None,
        "media_id": foto["id"] if foto else None,
        "slug_privato": privato["slug"] if privato else None,
        "token_privato": privato["access_token"] if privato else None,
        "slug_nascosto": nascosto["slug"] if nascosto else None,
        "media_privato": foto_privata["id"] if foto_privata else None,
    }
