"""Caricamento fotografie dal pannello, senza VPN.

I file vengono scritti sul Synology attraverso un mount dedicato in
scrittura (PHOTO_ROOT_RW). Questo modulo puo' soltanto CREARE cartelle e
file nuovi: non contiene alcuna operazione di cancellazione o
sovrascrittura, cosi' l'archivio esistente non e' mai a rischio. Se un
nome esiste gia', il nuovo file viene salvato con un suffisso numerico.
"""
import os
import re
import shutil
import unicodedata
from pathlib import Path

from fastapi import (APIRouter, Request, Form, Depends, File, UploadFile,
                     HTTPException, BackgroundTasks)
from fastapi.responses import HTMLResponse, JSONResponse

from ..database import get_db, log_event
from ..deps import require_admin_user, require_admin_api
from ..security import verify_csrf
from ..templating import templates

router = APIRouter(prefix="/admin/upload")

ALLOWED = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif",
           ".tif", ".tiff", ".mp4", ".mov", ".m4v", ".avi"}

CHUNK = 1024 * 1024  # 1 MB per volta: memoria costante anche con file grandi

# Quanto spazio deve restare libero sull'archivio perche' un caricamento
# venga accettato. Un NAS pieno non fa fallire solo il caricamento: fa
# fallire anche la scansione, le miniature e i backup, e lo si scopre
# quando e' gia' successo.
GB_MINIMI = 5


def _spazio_libero(percorso: Path):
    """Byte liberi sul disco che ospita quel percorso, None se non si sa."""
    try:
        return shutil.disk_usage(str(percorso)).free
    except OSError:
        return None


def _rw_root() -> Path:
    return Path(os.getenv("PHOTO_ROOT_RW", "/mnt/magazzino-rw"))


def _rw_ready() -> bool:
    root = _rw_root()
    return root.is_dir() and os.access(root, os.W_OK)


def _check_csrf(user, tok):
    if not verify_csrf(user.get("csrf", ""), tok):
        raise HTTPException(status_code=403, detail="Sessione non valida")


def _safe_name(name: str) -> str:
    """Ripulisce il nome del file mantenendolo riconoscibile."""
    name = os.path.basename(name or "").strip()
    name = unicodedata.normalize("NFC", name)
    name = name.replace("\\", "_").replace("/", "_")
    name = re.sub(r"[\x00-\x1f]", "", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name:
        raise HTTPException(status_code=400, detail="Nome file non valido")
    return name[:180]


def _safe_folder(name: str) -> str:
    """Nome cartella: niente separatori, niente percorsi relativi."""
    grezzo = (name or "").strip()
    if ("/" in grezzo) or ("\\" in grezzo) or (".." in grezzo) or grezzo.startswith("."):
        raise HTTPException(status_code=400, detail="Nome cartella non valido")
    pulito = _safe_name(grezzo)
    if pulito in (".", ".."):
        raise HTTPException(status_code=400, detail="Nome cartella non valido")
    return pulito


def _resolve_dest(node_rel_path: str, subfolder: str = "") -> Path:
    """Percorso di destinazione, verificato dentro la radice scrivibile."""
    root = _rw_root().resolve()
    dest = (root / node_rel_path)
    if subfolder:
        dest = dest / _safe_folder(subfolder)
    dest = dest.resolve()
    if root != dest and root not in dest.parents:
        raise HTTPException(status_code=400, detail="Destinazione non consentita")
    return dest


def _unique_path(folder: Path, filename: str) -> Path:
    """Non sovrascrive mai: se il nome esiste aggiunge -1, -2, ..."""
    stem, ext = os.path.splitext(filename)
    candidate = folder / filename
    i = 1
    while candidate.exists():
        candidate = folder / f"{stem}-{i}{ext}"
        i += 1
        if i > 9999:
            raise HTTPException(status_code=409, detail="Troppi file con lo stesso nome")
    return candidate


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def page(request: Request, user: dict = Depends(require_admin_user)):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, title, rel_path, depth FROM nodes ORDER BY rel_path").fetchall()
    destinazioni = [{"id": r["id"], "rel_path": r["rel_path"],
                     "label": r["rel_path"].replace("_", " ").replace("/", " / ")}
                    for r in rows]
    return templates.TemplateResponse(request, "admin/upload.html", {"user": user,
        "destinazioni": destinazioni, "rw_ready": _rw_ready(),
        "rw_path": str(_rw_root())})


@router.post("/file")
async def upload_file(request: Request,
                      csrf_token: str = Form(...),
                      node_id: int = Form(...),
                      subfolder: str = Form(""),
                      file: UploadFile = File(...),
                      user: dict = Depends(require_admin_api)):
    """Riceve un file e lo scrive sul NAS, senza toccare quelli esistenti."""
    _check_csrf(user, csrf_token)
    if not _rw_ready():
        raise HTTPException(status_code=503,
                            detail="Archivio non scrivibile: controlla il mount")

    filename = _safe_name(file.filename)
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED:
        raise HTTPException(status_code=415, detail=f"Formato non accettato: {ext}")

    with get_db() as conn:
        node = conn.execute("SELECT rel_path FROM nodes WHERE id=?",
                            (node_id,)).fetchone()
    if not node:
        raise HTTPException(status_code=404, detail="Album non trovato")

    folder = _resolve_dest(node["rel_path"], subfolder.strip())
    folder.mkdir(parents=True, exist_ok=True)

    libero = _spazio_libero(folder)
    if libero is not None and libero < GB_MINIMI * 1024 ** 3:
        raise HTTPException(
            status_code=507,
            detail=f"Spazio quasi esaurito sull'archivio "
                   f"({libero / 1024 ** 3:.1f} GB liberi): caricamento annullato")

    target = _unique_path(folder, filename)

    # Si scrive con un nome provvisorio e lo si cambia solo a fine
    # scrittura. Se la connessione cade a meta' — succede caricando da
    # telefono in mezzo a un campo di gara — quello che resta e' un file
    # ".parziale" che nessuno legge, invece di una fotografia troncata che
    # la scansione notturna pubblicherebbe come buona.
    parziale = target.with_name(target.name + ".parziale")
    scritti = 0
    try:
        with open(parziale, "wb") as out:
            while True:
                blocco = await file.read(CHUNK)
                if not blocco:
                    break
                out.write(blocco)
                scritti += len(blocco)
            out.flush()
            os.fsync(out.fileno())
        if scritti == 0:
            raise ValueError("file vuoto")
        parziale.rename(target)
    except Exception as exc:
        parziale.unlink(missing_ok=True)
        log_event("ERROR", "upload", f"Scrittura fallita: {target.name} ({exc})")
        raise HTTPException(status_code=500, detail="Scrittura non riuscita")
    finally:
        await file.close()

    log_event("INFO", "upload", f"Caricato {target.name} in {folder}")
    return JSONResponse({"ok": True, "filename": target.name, "bytes": scritti})


@router.post("/folder")
def create_folder(request: Request, csrf_token: str = Form(...),
                  node_id: int = Form(...), name: str = Form(...),
                  user: dict = Depends(require_admin_api)):
    """Crea una nuova sottocartella dentro un album esistente."""
    _check_csrf(user, csrf_token)
    if not _rw_ready():
        raise HTTPException(status_code=503, detail="Archivio non scrivibile")
    with get_db() as conn:
        node = conn.execute("SELECT rel_path FROM nodes WHERE id=?",
                            (node_id,)).fetchone()
    if not node:
        raise HTTPException(status_code=404, detail="Album non trovato")
    folder = _resolve_dest(node["rel_path"], name.strip())
    folder.mkdir(parents=True, exist_ok=True)
    log_event("INFO", "upload", f"Creata cartella {folder}")
    return JSONResponse({"ok": True, "path": str(folder)})


@router.post("/rescan")
def rescan(request: Request, background: BackgroundTasks,
           csrf_token: str = Form(...),
           user: dict = Depends(require_admin_api)):
    """Avvia in sottofondo la rilettura dell'archivio per pubblicare i nuovi file."""
    _check_csrf(user, csrf_token)
    from ..scanner import scan
    background.add_task(scan, full=False)
    return JSONResponse({"ok": True})
