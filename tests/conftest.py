"""Attrezzatura comune ai test.

I test girano contro l'applicazione vera, con il database vero in sola
lettura: nessun test scrive, cancella o modifica alcunche'. Sono controlli
di funzionamento, non di laboratorio: verificano che il sito risponda come
deve con i dati che ha davvero, che e' la cosa che interessa.

Si lanciano cosi', dalla cartella del sito:

    venv/bin/python -m pytest tests -q
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE))


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
    """Qualche identificativo vero preso dal database, per non inventarli."""
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
