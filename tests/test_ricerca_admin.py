"""Ricerca admin (/admin/tree/api/cerca): stessa logica multi-parola della
ricerca pubblica (tests/test_ricerca.py), ma con visibilita' estesa a
privati e nascosti, e dietro autenticazione admin."""
import re

import pytest

from app.database import get_db


def _titoli_in(testo: str) -> list:
    return re.findall(r"<h3>([^<]+)</h3>", testo)


def test_raduno_trova_risultati(client_admin):
    with get_db() as conn:
        riga = conn.execute(
            "SELECT id FROM nodes WHERE lower(title) LIKE '%raduno%' LIMIT 1").fetchone()
    if not riga:
        pytest.skip("nessun album 'raduno' nei dati reali")
    r = client_admin.get("/admin/tree/api/cerca", params={"q": "raduno"})
    assert r.status_code == 200
    body = r.json()
    assert len(body) > 0


def test_raduno_manno_trova_raduno_zona_industriale_manno(client_admin):
    with get_db() as conn:
        riga = conn.execute(
            "SELECT id, title FROM nodes WHERE "
            "lower(title) LIKE '%raduno%' AND lower(title) LIKE '%manno%'"
            " LIMIT 1").fetchone()
    if not riga:
        pytest.skip("nessun album 'raduno ... manno' nei dati reali")
    r = client_admin.get("/admin/tree/api/cerca", params={"q": "raduno manno"})
    titoli = [x["title"] for x in r.json()]
    assert riga["title"] in titoli


def test_ordine_parole_invertito_stesso_risultato(client_admin):
    with get_db() as conn:
        riga = conn.execute(
            "SELECT id, title FROM nodes WHERE "
            "lower(title) LIKE '%raduno%' AND lower(title) LIKE '%manno%'"
            " LIMIT 1").fetchone()
    if not riga:
        pytest.skip("nessun album 'raduno ... manno' nei dati reali")
    a = [x["title"] for x in client_admin.get(
        "/admin/tree/api/cerca", params={"q": "raduno manno"}).json()]
    b = [x["title"] for x in client_admin.get(
        "/admin/tree/api/cerca", params={"q": "manno raduno"}).json()]
    assert riga["title"] in a
    assert riga["title"] in b


def test_nome_parziale_funziona(client_admin):
    with get_db() as conn:
        riga = conn.execute(
            "SELECT id, title FROM nodes WHERE lower(title) LIKE '%raduno%' "
            "LIMIT 1").fetchone()
    if not riga:
        pytest.skip("nessun album 'raduno' nei dati reali")
    r = client_admin.get("/admin/tree/api/cerca", params={"q": "radun"})
    titoli = [x["title"] for x in r.json()]
    assert riga["title"] in titoli


def test_album_hidden_compare_nella_ricerca_admin(client_admin):
    with get_db() as conn:
        riga = conn.execute(
            "SELECT id, title FROM nodes WHERE hidden=1 AND length(title) > 3 "
            "LIMIT 1").fetchone()
    if not riga:
        pytest.skip("nessun album nascosto nei dati reali")
    parola = riga["title"].split()[0]
    if len(parola) < 3:
        pytest.skip("prima parola del titolo troppo corta")
    r = client_admin.get("/admin/tree/api/cerca", params={"q": parola})
    titoli = [x["title"] for x in r.json()]
    assert riga["title"] in titoli


def test_album_hidden_non_compare_nella_ricerca_pubblica(client):
    with get_db() as conn:
        riga = conn.execute(
            "SELECT id, title FROM nodes WHERE hidden=1 AND length(title) > 3 "
            "LIMIT 1").fetchone()
    if not riga:
        pytest.skip("nessun album nascosto nei dati reali")
    parola = riga["title"].split()[0]
    if len(parola) < 3:
        pytest.skip("prima parola del titolo troppo corta")
    r = client.get("/", params={"q": parola})
    assert riga["title"] not in _titoli_in(r.text)


def test_album_privato_compare_nella_ricerca_admin(client_admin):
    with get_db() as conn:
        riga = conn.execute(
            "SELECT id, title FROM nodes WHERE is_private=1 AND hidden=0 "
            "AND length(title) > 3 LIMIT 1").fetchone()
    if not riga:
        pytest.skip("nessun album privato nei dati reali")
    parola = riga["title"].split()[0]
    if len(parola) < 3:
        pytest.skip("prima parola del titolo troppo corta")
    r = client_admin.get("/admin/tree/api/cerca", params={"q": parola})
    titoli = [x["title"] for x in r.json()]
    assert riga["title"] in titoli


def test_query_inesistente_nessun_risultato(client_admin):
    r = client_admin.get("/admin/tree/api/cerca",
                         params={"q": "xyzxyznonesisteparola123456"})
    assert r.status_code == 200
    assert r.json() == []


def test_caratteri_speciali_non_causano_errori(client_admin):
    for q in ["%", "_", "'", "100%_'--", "'; DROP TABLE nodes; --"]:
        r = client_admin.get("/admin/tree/api/cerca", params={"q": q})
        assert r.status_code == 200
        assert isinstance(r.json(), list)
    # Verifica che la tabella nodes esista ancora (nessuna injection riuscita)
    with get_db() as conn:
        conn.execute("SELECT COUNT(*) FROM nodes").fetchone()


def test_query_vuota_nessun_risultato(client_admin):
    r = client_admin.get("/admin/tree/api/cerca", params={"q": ""})
    assert r.status_code == 200
    assert r.json() == []


def test_anonimo_non_accede(client):
    r = client.get("/admin/tree/api/cerca", params={"q": "raduno"}, follow_redirects=False)
    assert r.status_code in (302, 303, 401, 403)
