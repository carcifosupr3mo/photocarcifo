#!/usr/bin/env python3
"""Corregge larghezza e altezza delle fotografie ruotate.

Molte macchine registrano lo scatto in orizzontale e aggiungono
l'indicazione di rotazione. Se il sito legge le misure grezze, una
fotografia verticale sembra orizzontale e viene mostrata tagliata.
Questo programma rilegge l'indicazione e sistema i valori.
"""
import sys
from pathlib import Path

sys.path.insert(0, "/opt/photocarcifo")
from PIL import Image                       # noqa: E402
from app.config import get_settings         # noqa: E402
from app.database import get_db             # noqa: E402

RUOTATE = (5, 6, 7, 8)


def main() -> int:
    radice = get_settings().photo_root_path
    with get_db() as conn:
        righe = conn.execute(
            "SELECT id, rel_path, width, height FROM media "
            "WHERE kind='image' AND width > 0 AND height > 0").fetchall()

    totale = len(righe)
    print(f"Controllo {totale} fotografie…", flush=True)
    corrette, mancanti, errori = 0, 0, 0

    with get_db() as conn:
        for i, r in enumerate(righe, 1):
            if i % 5000 == 0:
                print(f"  {i}/{totale} — corrette finora: {corrette}", flush=True)
            percorso = radice / r["rel_path"]
            if not percorso.exists():
                mancanti += 1
                continue
            try:
                with Image.open(percorso) as img:
                    orient = img.getexif().get(274, 1)
            except Exception:
                errori += 1
                continue
            if orient in RUOTATE and r["width"] >= r["height"]:
                conn.execute("UPDATE media SET width=?, height=? WHERE id=?",
                             (r["height"], r["width"], r["id"]))
                corrette += 1

    print(f"Fatto. Corrette {corrette} fotografie ruotate."
          f"{f' {mancanti} file non trovati.' if mancanti else ''}"
          f"{f' {errori} non leggibili.' if errori else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
