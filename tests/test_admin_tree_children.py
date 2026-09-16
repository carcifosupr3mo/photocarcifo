"""api_children: la copertina e 'has_children' si calcolano ora in blocco
(poche query IN(...)) invece che una per nodo, ma il risultato deve
restare identico a prima per un nodo con piu' figli."""
from app.database import get_db


def test_api_children_campi_coerenti(client_admin):
    with get_db() as conn:
        genitore = conn.execute(
            "SELECT parent_id FROM nodes WHERE parent_id IS NOT NULL "
            "GROUP BY parent_id HAVING COUNT(*) > 1 LIMIT 1").fetchone()
    if not genitore:
        return  # nessun genitore con piu' di un figlio nei dati: niente da verificare
    parent_id = genitore["parent_id"]
    r = client_admin.get("/admin/tree/api/children", params={"parent": parent_id})
    assert r.status_code == 200
    nodi = r.json()
    assert len(nodi) > 1
    for n in nodi:
        for campo in ("id", "title", "name", "slug", "cover", "is_private",
                      "hidden", "downloads_enabled", "has_password",
                      "access_token", "total_media", "direct_media",
                      "depth", "has_children"):
            assert campo in n

    # Verifica indipendente: has_children calcolato riga per riga con il
    # vecchio metodo deve coincidere con quello restituito dall'endpoint.
    with get_db() as conn:
        for n in nodi:
            atteso = conn.execute(
                "SELECT 1 FROM nodes WHERE parent_id=? LIMIT 1",
                (n["id"],)).fetchone() is not None
            assert n["has_children"] == atteso, n["title"]
