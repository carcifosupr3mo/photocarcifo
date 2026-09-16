"""Interfaccia a riga di comando per operazioni di manutenzione.

Comandi:
    python -m app.cli scan         # scansione incrementale del NAS
    python -m app.cli scan --full  # forza rilettura dimensioni immagini
    python -m app.cli seed         # crea/aggiorna l'utente admin dal .env
    python -m app.cli initdb       # crea lo schema del database
    python -m app.cli numeri       # legge i numeri di gara delle foto in coda
    python -m app.cli numeri --all     # svuota tutta la coda in una volta
    python -m app.cli numeri --reset   # rilegge da zero tutte le fotografie

Usato dai timer systemd (scan, numeri) e al primo avvio (initdb + seed).
"""
import sys
from datetime import datetime, timezone

from .config import get_settings
from .database import init_db, get_db, log_event
from .scanner import scan
from .security import hash_password


def _seed_admin() -> None:
    """Crea l'utente admin se non esiste, usando le credenziali del .env.

    Non sovrascrive la password se l'utente esiste gia: dopo il primo
    avvio la password si cambia dalla dashboard, non dal .env.
    """
    settings = get_settings()
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE username=?", (settings.admin_username,)
        ).fetchone()
        if row:
            print(f"Utente admin '{settings.admin_username}' gia presente. Nessuna modifica.")
            return
        conn.execute(
            "INSERT INTO users(username, password_hash, is_admin, created_at) "
            "VALUES(?,?,1,?)",
            (settings.admin_username,
             hash_password(settings.admin_password),
             datetime.now(timezone.utc).isoformat()),
        )
    log_event("INFO", "system", f"Creato utente admin '{settings.admin_username}'")
    print(f"Utente admin '{settings.admin_username}' creato.")


def _leggi_numeri(argv: list[str]) -> int:
    """Legge i numeri di gara delle foto ancora in coda.

    Il motore OCR e' opzionale, quindi si importa solo qui: gli altri
    comandi non devono pagarne il caricamento.
    """
    from . import ocr
    from .numeri import azzera_ocr

    impostazioni = get_settings()
    init_db()

    if "--reset" in argv:
        with get_db() as conn:
            azzera_ocr(conn)
        print("Coda azzerata: tutte le foto verranno rilette.")

    if not ocr.disponibile():
        print("Nessun motore OCR installato.")
        print("Si attiva con:  venv/bin/pip install -r requirements-ocr.txt")
        return 1

    limite = None if ("--all" in argv or "--reset" in argv) else impostazioni.ocr_batch_size
    processi = ocr.processi_consigliati()
    print(f"Lettura numeri: {processi} processi in parallelo, "
          f"{ocr.in_coda()} foto in coda "
          f"({'tutte' if limite is None else f'max {limite} in questa passata'})")

    esito = ocr.elabora(limite=limite)
    if esito.get("saltato"):
        print("C'e' gia' una lettura in corso: questa passata non fa nulla.")
        print(f"  in coda: {esito['in_coda']}")
        return 0
    print("Fatto:")
    for chiave in ("analizzate", "con_numero", "numeri", "errori", "in_coda"):
        print(f"  {chiave}: {esito[chiave]}")
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        print("Uso: python -m app.cli [initdb|seed|scan|numeri] [--full|--all|--reset]")
        return 1

    cmd = argv[0]

    if cmd == "initdb":
        init_db()
        print("Database inizializzato.")
        return 0

    if cmd == "seed":
        init_db()
        _seed_admin()
        return 0

    if cmd == "scan":
        init_db()
        full = "--full" in argv[1:]
        result = scan(full=full)
        print("Scansione completata:")
        for k, v in result.items():
            print(f"  {k}: {v}")
        return 0

    if cmd == "numeri":
        return _leggi_numeri(argv[1:])

    print(f"Comando sconosciuto: {cmd}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
