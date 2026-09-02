"""Cestino: rimozione recuperabile di foto e album.

I file non vengono mai cancellati da questo modulo. Vengono SPOSTATI in
una cartella di cestino sul NAS (_CESTINO/<data-ora>/...), mantenendo il
percorso originale: cosi' il ripristino e' immediato e un errore non
comporta mai una perdita. Lo svuotamento definitivo si fa da DSM, dove si
vede esattamente cosa si sta eliminando.
"""
import os
import shutil
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from ..config import get_settings
from ..database import (get_db, log_event, ricalcola_date_album,
                        sottoalbero_like)
from ..deps import require_admin_user, require_admin_api
from ..indexnow import notify_indexnow
from ..security import verify_csrf
from ..templating import templates

router = APIRouter(prefix="/admin/trash")

CESTINO = "_CESTINO"


def _rw_root() -> Path:
    return Path(os.getenv("PHOTO_ROOT_RW", "/mnt/magazzino-rw"))


def _rw_ready() -> bool:
    root = _rw_root()
    return root.is_dir() and os.access(root, os.W_OK)


def _check_csrf(user, tok):
    if not verify_csrf(user.get("csrf", ""), tok):
        raise HTTPException(status_code=403, detail="Sessione non valida")


def _inside_root(p: Path) -> Path:
    """Garantisce che il percorso stia dentro la radice scrivibile."""
    root = _rw_root().resolve()
    p = p.resolve()
    if root != p and root not in p.parents:
        raise HTTPException(status_code=400, detail="Percorso non consentito")
    return p


def _lotto() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def _sposta(origine: Path, rel_path: str, lotto: str) -> Path:
    """Sposta un file o una cartella nel cestino, conservando il percorso."""
    destinazione = _rw_root() / CESTINO / lotto / rel_path
    destinazione.parent.mkdir(parents=True, exist_ok=True)
    _inside_root(destinazione.parent)
    finale = destinazione
    i = 1
    while finale.exists():
        finale = destinazione.with_name(f"{destinazione.name}.{i}")
        i += 1
    shutil.move(str(origine), str(finale))
    return finale


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def page(request: Request, user: dict = Depends(require_admin_user)):
    lotti = []
    base = _rw_root() / CESTINO
    if base.is_dir():
        for d in sorted(base.iterdir(), reverse=True):
            if not d.is_dir():
                continue
            file_count = sum(1 for _ in d.rglob("*") if _.is_file())
            lotti.append({"nome": d.name, "file": file_count})
    return templates.TemplateResponse(request, "admin/trash.html", {"user": user, "lotti": lotti,
        "rw_ready": _rw_ready(), "cestino": str(base)})


@router.post("/media")
def trash_media(request: Request, csrf_token: str = Form(...),
                ids: str = Form(...), user: dict = Depends(require_admin_api)):
    """Sposta nel cestino le foto indicate e le toglie dal sito."""
    _check_csrf(user, csrf_token)
    if not _rw_ready():
        raise HTTPException(status_code=503, detail="Archivio non scrivibile")

    id_list = [int(x) for x in ids.split(",") if x.strip().isdigit()][:2000]
    if not id_list:
        raise HTTPException(status_code=400, detail="Nessuna foto indicata")

    lotto = _lotto()
    spostati, mancanti = 0, 0
    # Gli errori si annotano qui e si scrivono nel registro DOPO aver chiuso
    # la transazione: log_event apre una connessione propria e, con una
    # cancellazione gia' avviata, resterebbe in attesa di questa, bloccando
    # l'intera operazione.
    errori: list[str] = []
    segnaposto = ",".join("?" * len(id_list))
    with get_db() as conn:
        righe = conn.execute(
            f"SELECT id, rel_path, node_id FROM media WHERE id IN ({segnaposto})",
            id_list).fetchall()
        for r in righe:
            origine = _rw_root() / r["rel_path"]
            try:
                if origine.exists():
                    _inside_root(origine)
                    _sposta(origine, r["rel_path"], lotto)
                    spostati += 1
                else:
                    mancanti += 1
                conn.execute("DELETE FROM media WHERE id=?", (r["id"],))
            except HTTPException:
                raise
            except Exception as exc:
                errori.append(f"{r['rel_path']}: {exc}")
        _ricalcola_conteggi(conn)

    for messaggio in errori:
        log_event("ERROR", "trash", f"Spostamento fallito {messaggio}")
    log_event("INFO", "trash", f"Nel cestino {spostati} file (lotto {lotto})")
    return JSONResponse({"ok": True, "spostati": spostati,
                         "mancanti": mancanti, "lotto": lotto})


@router.post("/node/{node_id}")
def trash_node(request: Request, node_id: int, background: BackgroundTasks,
               csrf_token: str = Form(...), user: dict = Depends(require_admin_api)):
    """Sposta nel cestino un intero album con tutto il suo contenuto."""
    _check_csrf(user, csrf_token)
    if not _rw_ready():
        raise HTTPException(status_code=503, detail="Archivio non scrivibile")

    with get_db() as conn:
        node = conn.execute("SELECT id, rel_path, title FROM nodes WHERE id=?",
                            (node_id,)).fetchone()
        if not node:
            raise HTTPException(status_code=404, detail="Album non trovato")
        rel = node["rel_path"]
        origine = _rw_root() / rel
        lotto = _lotto()
        if origine.exists():
            _inside_root(origine)
            _sposta(origine, rel, lotto)
        # ESCAPE obbligatorio: senza, il "_" nei nomi delle cartelle e' un
        # jolly e questa cancellazione porterebbe via anche album estranei.
        like = sottoalbero_like(rel)
        # Slug degli album pubblici che stanno per sparire, letti PRIMA
        # della DELETE qui sotto: IndexNow va avvisato che quelle pagine
        # non esistono piu', cosi' Bing le ricontrolla e le toglie dai
        # risultati invece di scoprirlo da solo al prossimo giro, magari
        # tra settimane.
        pubblici = conn.execute(
            "SELECT slug FROM nodes WHERE (rel_path=? OR rel_path LIKE ? ESCAPE '\\') "
            "AND is_private=0 AND hidden=0 AND total_media>0",
            (rel, like)).fetchall()
        conn.execute(
            "DELETE FROM media WHERE node_id IN "
            "(SELECT id FROM nodes WHERE rel_path=? OR rel_path LIKE ? ESCAPE '\\')",
            (rel, like))
        conn.execute("DELETE FROM nodes WHERE rel_path=? OR rel_path LIKE ? ESCAPE '\\'",
                     (rel, like))
        _ricalcola_conteggi(conn)

    if pubblici:
        base = get_settings().site_url.rstrip("/")
        urls = [f"{base}/n/{r['slug']}" for r in pubblici]
        background.add_task(notify_indexnow, urls)

    log_event("INFO", "trash", f"Album '{node['title']}' nel cestino (lotto {lotto})")
    return JSONResponse({"ok": True, "lotto": lotto})


@router.post("/restore")
def restore(request: Request, csrf_token: str = Form(...),
            lotto: str = Form(...), user: dict = Depends(require_admin_api)):
    """Riporta al loro posto tutti i file di un gruppo del cestino."""
    _check_csrf(user, csrf_token)
    if not _rw_ready():
        raise HTTPException(status_code=503, detail="Archivio non scrivibile")
    if ("/" in lotto) or ("\\" in lotto) or (".." in lotto) or lotto.startswith("."):
        raise HTTPException(status_code=400, detail="Gruppo non valido")

    base = _inside_root(_rw_root() / CESTINO / lotto)
    if not base.is_dir():
        raise HTTPException(status_code=404, detail="Gruppo non trovato")

    ripristinati = 0
    for sorgente in sorted(base.rglob("*")):
        if not sorgente.is_file():
            continue
        rel = sorgente.relative_to(base)
        destinazione = _inside_root(_rw_root() / rel)
        destinazione.parent.mkdir(parents=True, exist_ok=True)
        finale = destinazione
        i = 1
        while finale.exists():
            finale = destinazione.with_name(f"{destinazione.stem}-{i}{destinazione.suffix}")
            i += 1
        shutil.move(str(sorgente), str(finale))
        ripristinati += 1

    log_event("INFO", "trash", f"Ripristinati {ripristinati} file dal gruppo {lotto}")
    return JSONResponse({"ok": True, "ripristinati": ripristinati})


def _ricalcola_conteggi(conn):
    """Riallinea i contatori degli album dopo una rimozione."""
    conn.execute(
        "UPDATE nodes SET direct_media = "
        "(SELECT COUNT(*) FROM media WHERE media.node_id = nodes.id)")
    # substr al posto di LIKE: il "_" nei nomi delle cartelle e' un jolly e
    # gonfierebbe i conteggi con le foto di album estranei.
    conn.execute(
        "UPDATE nodes SET total_media = ("
        " SELECT COUNT(*) FROM media m JOIN nodes n2 ON n2.id = m.node_id"
        " WHERE n2.rel_path = nodes.rel_path"
        " OR substr(n2.rel_path, 1, length(nodes.rel_path) + 1)"
        "    = nodes.rel_path || '/')")
    ricalcola_date_album(conn)
