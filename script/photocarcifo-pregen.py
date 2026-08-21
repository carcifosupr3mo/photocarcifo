"""Prepara in anticipo le miniature, cosi' gli album si aprono subito.

Gira di notte e lavora solo su cio' che manca: le immagini gia' in cache
vengono saltate. Prepara la miniatura della griglia, la versione doppia per
gli schermi ad alta densita' e, se richiesto, anche l'anteprima a schermo
intero. Si ferma da solo al tempo massimo o quando lo spazio libero scende
sotto la soglia di sicurezza.

Il lavoro e' diviso su piu' processi: ridimensionare e comprimere e' lavoro
di CPU pura, quindi i thread di Python non servirebbero a nulla. Il numero
di processi si adatta ai core disponibili e lascia sempre respiro al sito.
"""
import multiprocessing as mp
import os
import shutil
import sys
import time

sys.path.insert(0, "/opt/photocarcifo")

from app.config import get_settings          # noqa: E402
from app.database import get_db, log_event   # noqa: E402
from app.thumbnails import (                 # noqa: E402
    prepara_gruppo, SIZE_SMALL, SIZE_CARD, SIZE_MEDIUM,
    FORMATO_JPEG, FORMATO_WEBP, FORMATO_AVIF)

MINUTI_MASSIMI = int(os.getenv("PREGEN_MINUTI", "45"))
GB_LIBERI_MINIMI = float(os.getenv("PREGEN_GB_MINIMI", "5"))
# Con PREGEN_ANTEPRIME=1 prepara anche le anteprime a schermo intero.
ANTEPRIME = os.getenv("PREGEN_ANTEPRIME", "0") == "1"
# 0 = decide da solo in base ai core disponibili.
PROCESSI = int(os.getenv("PREGEN_PROCESSI", "0"))

# Quante foto affidare ai processi prima di ricontrollare tempo e spazio.
BLOCCO = 240


def gb_liberi(percorso) -> float:
    return shutil.disk_usage(str(percorso)).free / (1024 ** 3)


def processi_da_usare() -> int:
    if PROCESSI > 0:
        return PROCESSI
    # Si lascia un core al sito: deve restare reattivo mentre si lavora.
    return max(1, min((os.cpu_count() or 2) - 1, 12))


# Si preparano i due formati moderni: AVIF per i browser recenti (un terzo
# in meno del WebP) e WebP per quelli di prima (il 40% in meno del JPEG).
#
# Il JPEG non si prepara piu'. Lo riceve solo chi non dichiara di saper
# leggere ne' l'uno ne' l'altro, cioe' browser anteriori al 2020: teneva
# 16,4 GB di copie pronte, il 59% di tutta la cache, per un pubblico che
# in pratica non esiste. Chi lo chiede se lo vede generare al momento in
# mezzo secondo, e da quel momento resta in cache anche per lui.
#
# FORMATO_JPEG resta importato di proposito: e' ancora il formato delle
# anteprime per le chat, e chi legge questo elenco deve vedere che l'assenza
# e' una scelta e non una dimenticanza.
FORMATI = (FORMATO_WEBP, FORMATO_AVIF)


def _prepara(compito):
    """Eseguito nei processi figli: genera le miniature di una fotografia.

    Tutte insieme, non una per una: l'originale viene letto dal NAS e
    decodificato una volta sola invece di sei. Su una fotografia da 14 MB
    fa la differenza fra 4,9 e 2,7 secondi.
    """
    rel_path, mtime, kind, misure = compito
    try:
        return prepara_gruppo(rel_path, mtime, kind, misure, FORMATI)
    except Exception:
        return 0, len(misure) * len(FORMATI)


def main() -> int:
    settings = get_settings()
    cache = settings.thumb_cache_path
    cache.mkdir(parents=True, exist_ok=True)

    misure = [SIZE_SMALL, SIZE_CARD]
    if ANTEPRIME:
        misure.append(SIZE_MEDIUM)
    print(f"Misure preparate: {', '.join(misure)}")

    liberi = gb_liberi(cache)
    if liberi < GB_LIBERI_MINIMI:
        print(f"Spazio insufficiente: {liberi:.1f} GB liberi, "
              f"soglia {GB_LIBERI_MINIMI} GB. Nessuna immagine preparata.")
        log_event("WARNING", "cache", f"Pregenerazione saltata: {liberi:.1f} GB liberi")
        return 0

    scadenza = time.time() + MINUTI_MASSIMI * 60
    with get_db() as conn:
        righe = conn.execute(
            "SELECT m.rel_path, m.mtime, m.kind FROM media m "
            "JOIN nodes n ON n.id = m.node_id "
            "WHERE n.hidden = 0 "
            "ORDER BY n.sort_order, m.id"
        ).fetchall()

    compiti = [(r["rel_path"], r["mtime"], r["kind"], misure) for r in righe]
    quanti = processi_da_usare()
    print(f"{len(compiti)} fotografie da controllare, {quanti} processi")

    fatte, media_visti, errori = 0, 0, 0
    # spawn invece di fork: i processi figli partono puliti, senza ereditare
    # la connessione al database aperta qui sopra.
    pool = mp.get_context("spawn").Pool(processes=quanti)
    try:
        for inizio in range(0, len(compiti), BLOCCO):
            if time.time() > scadenza:
                print("Tempo massimo raggiunto: riprendo la prossima notte.")
                break
            if gb_liberi(cache) < GB_LIBERI_MINIMI:
                print("Spazio in esaurimento: mi fermo qui.")
                break
            for f, e in pool.map(_prepara, compiti[inizio:inizio + BLOCCO]):
                fatte += f
                errori += e
                media_visti += 1
    finally:
        pool.close()
        pool.join()

    messaggio = (f"Immagini pronte: {fatte} file su {media_visti} foto"
                 f"{f', {errori} non riusciti' if errori else ''}. "
                 f"Spazio libero: {gb_liberi(cache):.1f} GB")
    print(messaggio)
    log_event("INFO", "cache", messaggio)
    return 0


if __name__ == "__main__":
    sys.exit(main())
