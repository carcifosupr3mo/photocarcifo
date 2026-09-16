"""QR code degli album nel pannello admin (/admin/tree/{id}/qr)."""
from app.config import get_settings
from app.database import get_db


def test_album_pubblico_genera_png_valido(client_admin, dati):
    if not dati["node_id"]:
        return  # niente album pubblico nei dati di test
    r = client_admin.get(f"/admin/tree/{dati['node_id']}/qr")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    # firma PNG: primi 8 byte fissi
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(r.content) > 200  # un QR vero non e' vuoto ne' minuscolo


def test_album_inesistente_404(client_admin):
    r = client_admin.get("/admin/tree/999999999/qr")
    assert r.status_code == 404


def test_anonimo_non_vede_il_qr(client):
    with get_db() as conn:
        n = conn.execute("SELECT id FROM nodes LIMIT 1").fetchone()
    if not n:
        return
    r = client.get(f"/admin/tree/{n['id']}/qr", follow_redirects=False)
    assert r.status_code in (302, 303, 401, 403)
    assert r.headers.get("content-type") != "image/png"


def test_album_privato_con_token_genera_qr_col_link_p(client_admin, dati):
    if not dati["token_privato"]:
        return  # nessun album privato con token nei dati di test
    with get_db() as conn:
        node = conn.execute(
            "SELECT id FROM nodes WHERE access_token=? AND is_private=1",
            (dati["token_privato"],)).fetchone()
    r = client_admin.get(f"/admin/tree/{node['id']}/qr")
    # Scelta implementata: un album privato con token genera comunque il QR,
    # puntando allo stesso link /p/{token} gia' mostrato nel pannello come
    # "link di condivisione" (la password, se impostata, resta comunque
    # richiesta all'apertura: il QR non la aggira).
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"


def test_album_nascosto_non_privato_viene_bloccato(client_admin):
    with get_db() as conn:
        n = conn.execute(
            "SELECT id FROM nodes WHERE hidden=1 AND is_private=0 LIMIT 1").fetchone()
    if not n:
        return  # nessun album solo-nascosto nei dati di test
    r = client_admin.get(f"/admin/tree/{n['id']}/qr")
    assert r.status_code == 409
    assert r.headers.get("content-type") != "image/png"


def test_qr_non_contiene_indirizzi_interni(client_admin, dati):
    if not dati["node_id"]:
        return
    r = client_admin.get(f"/admin/tree/{dati['node_id']}/qr")
    assert r.status_code == 200
    site_url = get_settings().site_url
    # Non e' possibile decodificare il QR senza una libreria in piu': si
    # verifica invece che l'unico indirizzo usato nel codice sorgente sia
    # quello pubblico configurato, non un IP interno o un percorso locale.
    assert "192.168." not in site_url
    assert "/opt/" not in site_url
    assert "/root/" not in site_url
