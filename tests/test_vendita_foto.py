"""Test mirati: Fase 1 vendita foto eventi (sales_enabled/photo_price_cents).

Nessun pagamento reale in questa fase: solo modello dati, admin, e un
bottone informativo nel lightbox. Verifica che l'attivazione della
vendita non tocchi in nessun modo la privacy esistente (privato/nascosto
restano indipendenti da sales_enabled).
"""
import re

import pytest

from app.database import get_db


def _album_con_foto(conn, quante=3):
    return conn.execute(
        "SELECT n.id, n.slug FROM nodes n JOIN media m ON m.node_id=n.id "
        "WHERE n.is_private=0 AND n.hidden=0 "
        "GROUP BY n.id HAVING COUNT(m.id) >= ? LIMIT 1", (quante,)).fetchone()


def _csrf(client_admin):
    r = client_admin.get("/admin/tree")
    tok = re.search(r'id="csrf"[^>]*value="([^"]+)"', r.text)
    if not tok:
        pytest.skip("campo di sicurezza non trovato nella pagina")
    return tok.group(1)


def _reset_vendita(node_id):
    """Le colonne sales_enabled/photo_price_cents sono globali sul nodo:
    ripristina lo stato di partenza dopo ogni test, cosi' i test non si
    influenzano a vicenda (stesso DB isolato per l'intera sessione)."""
    with get_db() as conn:
        conn.execute(
            "UPDATE nodes SET sales_enabled=0, photo_price_cents=0 WHERE id=?",
            (node_id,))
        conn.commit()


# --- Album vendita OFF (default) --------------------------------------------

def test_album_vendita_off_di_default(client_admin):
    with get_db() as conn:
        a = _album_con_foto(conn)
    assert a is not None, "serve un album pubblico con almeno 3 foto nel DB di test"
    with get_db() as conn:
        riga = conn.execute(
            "SELECT sales_enabled, photo_price_cents FROM nodes WHERE id=?",
            (a["id"],)).fetchone()
    assert riga["sales_enabled"] == 0
    assert riga["photo_price_cents"] == 0


def test_pagina_pubblica_senza_vendita_non_ha_attributi_sales(client, dati):
    assert dati["slug"], "serve un album pubblico nel DB di test"
    r = client.get(f"/n/{dati['slug']}")
    assert r.status_code == 200
    assert 'data-sales="1"' not in r.text
    assert "data-price-cents" not in r.text


# --- Attivazione vendita via admin -------------------------------------------

def test_admin_attiva_vendita_con_prezzo(client_admin):
    with get_db() as conn:
        a = _album_con_foto(conn)
    tok = _csrf(client_admin)
    try:
        r = client_admin.post(f"/admin/tree/{a['id']}/vendita",
                              data={"csrf_token": tok, "sales_enabled": "1",
                                    "photo_price_cents": "1000"})
        assert r.status_code == 200
        body = r.json()
        assert body["sales_enabled"] is True
        assert body["photo_price_cents"] == 1000

        with get_db() as conn:
            riga = conn.execute(
                "SELECT sales_enabled, photo_price_cents FROM nodes WHERE id=?",
                (a["id"],)).fetchone()
        assert riga["sales_enabled"] == 1
        assert riga["photo_price_cents"] == 1000
    finally:
        _reset_vendita(a["id"])


def test_admin_prezzo_non_numerico_diventa_zero(client_admin):
    """L'endpoint non deve mai accettare un float o un valore assurdo:
    input non numerico ricade su 0 invece di far esplodere la richiesta
    (vedi try/except ValueError in admin_nodes.py:vendita())."""
    with get_db() as conn:
        a = _album_con_foto(conn)
    tok = _csrf(client_admin)
    try:
        r = client_admin.post(f"/admin/tree/{a['id']}/vendita",
                              data={"csrf_token": tok, "sales_enabled": "1",
                                    "photo_price_cents": "non-un-numero"})
        assert r.status_code == 200
        assert r.json()["photo_price_cents"] == 0
    finally:
        _reset_vendita(a["id"])


def test_admin_prezzo_negativo_diventa_zero(client_admin):
    with get_db() as conn:
        a = _album_con_foto(conn)
    tok = _csrf(client_admin)
    try:
        r = client_admin.post(f"/admin/tree/{a['id']}/vendita",
                              data={"csrf_token": tok, "sales_enabled": "1",
                                    "photo_price_cents": "-500"})
        assert r.status_code == 200
        assert r.json()["photo_price_cents"] == 0
    finally:
        _reset_vendita(a["id"])


def test_endpoint_vendita_richiede_csrf(client_admin):
    with get_db() as conn:
        a = _album_con_foto(conn)
    r = client_admin.post(f"/admin/tree/{a['id']}/vendita",
                          data={"sales_enabled": "1", "photo_price_cents": "1000"})
    assert r.status_code in (400, 403, 422)
    with get_db() as conn:
        riga = conn.execute("SELECT sales_enabled FROM nodes WHERE id=?",
                            (a["id"],)).fetchone()
    assert riga["sales_enabled"] == 0, "senza CSRF valido non deve cambiare nulla"


def test_endpoint_vendita_richiede_login_admin(client):
    """Stesso endpoint, ma con il client pubblico (nessuna sessione admin)."""
    with get_db() as conn:
        a = _album_con_foto(conn)
    r = client.post(f"/admin/tree/{a['id']}/vendita",
                    data={"csrf_token": "x", "sales_enabled": "1",
                          "photo_price_cents": "1000"})
    assert r.status_code in (401, 403, 404)


# --- Pagina pubblica con vendita attiva --------------------------------------

def test_pagina_pubblica_con_vendita_mostra_attributi_sales(client_admin):
    with get_db() as conn:
        a = _album_con_foto(conn)
    tok = _csrf(client_admin)
    try:
        client_admin.post(f"/admin/tree/{a['id']}/vendita",
                          data={"csrf_token": tok, "sales_enabled": "1",
                                "photo_price_cents": "1500"})
        r = client_admin.get(f"/n/{a['slug']}")
        assert r.status_code == 200
        assert 'data-sales="1"' in r.text
        assert 'data-price-cents="1500"' in r.text
    finally:
        _reset_vendita(a["id"])


# --- Privacy: sales_enabled non deve mai bypassare privato/nascosto --------

def test_album_privato_con_vendita_resta_privato(client_admin, dati):
    """Attivare la vendita su un album privato non lo rende pubblico: il
    client SENZA sessione admin deve continuare a non poterlo vedere."""
    if not dati["slug_privato"]:
        pytest.skip("nessun album privato nel DB di test")
    with get_db() as conn:
        priv = conn.execute("SELECT id FROM nodes WHERE slug=?",
                            (dati["slug_privato"],)).fetchone()
    tok = _csrf(client_admin)
    try:
        client_admin.post(f"/admin/tree/{priv['id']}/vendita",
                          data={"csrf_token": tok, "sales_enabled": "1",
                                "photo_price_cents": "1000"})
        with get_db() as conn:
            riga = conn.execute(
                "SELECT is_private, hidden FROM nodes WHERE id=?",
                (priv["id"],)).fetchone()
        assert riga["is_private"] == 1, "sales_enabled non deve toccare is_private"
        assert riga["hidden"] == 0
    finally:
        _reset_vendita(priv["id"])


def test_album_nascosto_con_vendita_resta_nascosto(client_admin, dati):
    if not dati["slug_nascosto"]:
        pytest.skip("nessun album nascosto nel DB di test")
    with get_db() as conn:
        nasc = conn.execute("SELECT id FROM nodes WHERE slug=?",
                            (dati["slug_nascosto"],)).fetchone()
    tok = _csrf(client_admin)
    try:
        client_admin.post(f"/admin/tree/{nasc['id']}/vendita",
                          data={"csrf_token": tok, "sales_enabled": "1",
                                "photo_price_cents": "1000"})
        with get_db() as conn:
            riga = conn.execute("SELECT hidden FROM nodes WHERE id=?",
                                (nasc["id"],)).fetchone()
        assert riga["hidden"] == 1, "sales_enabled non deve toccare hidden"
    finally:
        _reset_vendita(nasc["id"])
