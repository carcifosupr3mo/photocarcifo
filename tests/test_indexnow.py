"""Notifica IndexNow (app/indexnow.py).

Come in test_ban_alert.py: nessuna chiamata di rete reale durante la
suite. Ogni test che passa da notify_indexnow() monkeypatcha
urllib.request.urlopen.
"""
import io
import urllib.error

import pytest

from app import indexnow
from app.config import get_settings


@pytest.fixture(autouse=True)
def config_test(monkeypatch):
    """SITE_URL e chiave fissi per tutta la suite, indipendenti da .env."""
    monkeypatch.setenv("SITE_URL", "https://photocarcifo.ch")
    monkeypatch.setenv("INDEXNOW_KEY", "c346e78ff7cc905c8ca37f325f01d3f2")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def blocca_rete(monkeypatch):
    """Qualunque chiamata di rete reale durante un test che non l'abbia
    esplicitamente attesa deve far fallire il test, non provare a
    contattare davvero IndexNow."""
    def esplodi(*a, **k):
        raise AssertionError("notify_indexnow ha tentato una chiamata di rete reale")
    monkeypatch.setattr("urllib.request.urlopen", esplodi)


class _RispostaFinta:
    def __init__(self, status=200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# --- url_indicizzabile: cosa e' e cosa non e' una URL da notificare ---

@pytest.mark.parametrize("url,atteso", [
    ("https://photocarcifo.ch/n/bmx-2026", True),
    ("https://photocarcifo.ch/", True),
    ("https://photocarcifo.ch/en/n/bmx-2026", True),
    ("https://photocarcifo.ch/chi-sono", True),
    ("https://photocarcifo.ch/n/bmx-2026?page=2", False),
    ("https://photocarcifo.ch/?q=test", False),
    ("https://photocarcifo.ch/admin/tree", False),
    ("https://photocarcifo.ch/p/token123", False),
    ("https://photocarcifo.ch/f/token123", False),
    ("https://photocarcifo.ch/fs/token123", False),
    ("https://photocarcifo.ch/download/1", False),
    ("https://photocarcifo.ch/zip/1", False),
    ("https://photocarcifo.ch/video/1", False),
    ("https://photocarcifo.ch/thumb/1", False),
    ("https://photocarcifo.ch/thumb2x/1", False),
    ("https://photocarcifo.ch/cover/1", False),
    ("https://photocarcifo.ch/preview/1", False),
    ("https://photocarcifo.ch/preferiti/x", False),
    ("https://photocarcifo.ch/mie-preferite", False),
    ("https://photocarcifo.ch/radunimoto", False),
    ("https://photocarcifo.ch/lingua/en", False),
    ("https://photocarcifo.ch/healthz", False),
    ("https://photocarcifo.ch/search", False),
    # "it" non e' un prefisso valido (e' la lingua predefinita, l'italiano
    # non ha prefisso nell'indirizzo — vedi lingue.PREFISSI): un indirizzo
    # che iniziasse letteralmente con /it/ non corrisponde a nessuna route
    # reale del sito, ma /download/ dopo la barra e' comunque riconosciuto.
    ("https://photocarcifo.ch/download/1", False),
    ("https://photocarcifo.ch/en/admin/tree", False),
    # Varianti "camuffate" dello stesso indirizzo riservato: il filtro deve
    # riconoscerle comunque, non solo la forma scritta in modo canonico.
    ("https://photocarcifo.ch/P/token123", False),          # maiuscolo
    ("https://photocarcifo.ch//p/token123", False),         # barra doppia
    ("https://photocarcifo.ch/%2fp/token123", False),       # percent-encoding
    ("https://photocarcifo.ch/./p/token123", False),        # segmento "."
    ("https://photocarcifo.ch/ADMIN/tree", False),          # maiuscolo
    ("https://evil.example/n/bmx-2026", False),
    ("https://photocarcifo.ch.evil.example/n/bmx", False),
    ("http://photocarcifo.ch/n/bmx-2026", False),
    ("ftp://photocarcifo.ch/n/bmx-2026", False),
    ("non-una-url", False),
    ("", False),
])
def test_url_indicizzabile(url, atteso):
    assert indexnow.url_indicizzabile(url) is atteso


# --- notify_indexnow: filtri, dedup, chiave assente, errori di rete ---

def test_chiave_assente_non_manda_nulla(monkeypatch, blocca_rete):
    monkeypatch.setenv("INDEXNOW_KEY", "")
    get_settings.cache_clear()
    assert indexnow.notify_indexnow(["https://photocarcifo.ch/n/x"]) is False


def test_nessuna_url_valida_non_manda_nulla(blocca_rete):
    assert indexnow.notify_indexnow(["https://evil.example/n/x", "?page=2"]) is False


def test_url_singola_stringa_accettata(monkeypatch):
    catturato = {}

    def urlopen_finto(req, timeout):
        catturato["corpo"] = req.data
        return _RispostaFinta(200)

    monkeypatch.setattr("urllib.request.urlopen", urlopen_finto)
    ok = indexnow.notify_indexnow("https://photocarcifo.ch/n/singolo")
    assert ok is True
    assert b"singolo" in catturato["corpo"]


def test_duplicati_eliminati_e_url_esterne_scartate(monkeypatch):
    catturato = {}

    def urlopen_finto(req, timeout):
        catturato["corpo"] = req.data
        return _RispostaFinta(200)

    monkeypatch.setattr("urllib.request.urlopen", urlopen_finto)
    ok = indexnow.notify_indexnow([
        "https://photocarcifo.ch/n/a",
        "https://photocarcifo.ch/n/a",           # duplicato esatto
        "https://photocarcifo.ch/n/b",
        "https://evil.example/n/c",               # dominio estraneo
        "https://photocarcifo.ch/admin/tree",     # tecnica/riservata
    ])
    assert ok is True
    import json
    corpo = json.loads(catturato["corpo"])
    assert sorted(corpo["urlList"]) == [
        "https://photocarcifo.ch/n/a", "https://photocarcifo.ch/n/b"]
    assert corpo["host"] == "photocarcifo.ch"
    assert corpo["key"] == "c346e78ff7cc905c8ca37f325f01d3f2"
    assert corpo["keyLocation"] == (
        "https://photocarcifo.ch/c346e78ff7cc905c8ca37f325f01d3f2.txt")


def test_errore_http_non_solleva_eccezioni(monkeypatch):
    def urlopen_finto(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {}, io.BytesIO(b""))

    monkeypatch.setattr("urllib.request.urlopen", urlopen_finto)
    assert indexnow.notify_indexnow(["https://photocarcifo.ch/n/x"]) is False


def test_status_inatteso_conta_come_fallimento(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout: _RispostaFinta(500))
    assert indexnow.notify_indexnow(["https://photocarcifo.ch/n/x"]) is False


def test_timeout_non_blocca_e_non_solleva(monkeypatch):
    def urlopen_finto(req, timeout):
        raise TimeoutError("simulato")

    monkeypatch.setattr("urllib.request.urlopen", urlopen_finto)
    assert indexnow.notify_indexnow(["https://photocarcifo.ch/n/x"]) is False


def test_status_202_accettato(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout: _RispostaFinta(202))
    assert indexnow.notify_indexnow(["https://photocarcifo.ch/n/x"]) is True
