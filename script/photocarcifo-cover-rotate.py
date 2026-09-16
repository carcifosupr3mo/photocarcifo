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
    _prepara_le_copertine()


def _prepara_le_copertine():
    """Prepara subito l'immagine di ogni copertina appena scelta.

    Scegliere la copertina e prepararla sono due cose diverse, e finora si
    faceva solo la prima: ogni notte le copertine cambiavano e restavano da
    costruire, cosi' il primo visitatore del mattino se le vedeva generare
    una per una mentre aspettava. Su una fotografia sono due o tre decimi
    di secondo, ma su un video il fotogramma va estratto con ffmpeg da un
    file che sta sul NAS: misurato il 22/08/2026, undici secondi e mezzo
    per una pagina con un solo album video dentro.

    Sono centoquaranta immagini, una per album: pochi secondi in tutto, e
    di notte, quando non aspetta nessuno.
    """
    from app.thumbnails import (prepara_gruppo, SIZE_COVER,
                                FORMATO_WEBP, FORMATO_AVIF)
    fatte = saltate = errori = 0
    with get_db() as conn:
        righe = conn.execute(
            "SELECT m.rel_path, m.mtime, m.kind FROM nodes n "
            "JOIN media m ON m.id = n.cover_media_id "
            "WHERE n.cover_media_id IS NOT NULL").fetchall()
    for r in righe:
        try:
            f, e = prepara_gruppo(r["rel_path"], r["mtime"], r["kind"],
                                  [SIZE_COVER], (FORMATO_WEBP, FORMATO_AVIF))
            fatte += f
            errori += e
            if not f and not e:
                saltate += 1
        except Exception:
            errori += 1
    messaggio = (f"Copertine preparate: {fatte} nuove, {saltate} gia' pronte"
                 f"{f', {errori} non riuscite' if errori else ''}")
    print(messaggio)
    log_event("INFO", "cover", messaggio)

if __name__ == "__main__":
    main()
