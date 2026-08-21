#!/opt/photocarcifo/venv/bin/python
"""Rotazione giornaliera delle copertine degli album pubblici.

Per ogni nodo pubblico (is_private=0) sceglie a caso una foto presente
nel proprio sottoalbero e la imposta come copertina. Gli album privati
non vengono toccati.
"""
import sys
sys.path.insert(0, "/opt/photocarcifo")

from app.database import get_db, log_event

def main():
    cambiati = 0
    with get_db() as conn:
        nodi = conn.execute(
            "SELECT id, rel_path FROM nodes WHERE is_private=0"
        ).fetchall()
        for n in nodi:
            row = conn.execute(
                "SELECT m.id FROM media m JOIN nodes nn ON nn.id = m.node_id "
                "WHERE (nn.rel_path = ? OR nn.rel_path LIKE ?) "
                "AND m.kind = 'image' AND nn.is_private = 0 AND nn.hidden = 0 "
                "ORDER BY RANDOM() LIMIT 1",
                (n["rel_path"], n["rel_path"] + "/%"),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE nodes SET cover_media_id=? WHERE id=?",
                    (row["id"], n["id"]),
                )
                cambiati += 1
    log_event("INFO", "cover", f"Copertine ruotate: {cambiati}")
    print(f"Copertine aggiornate: {cambiati}")

if __name__ == "__main__":
    main()
