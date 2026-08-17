"""Router media: miniature, anteprime, download singolo, video, ZIP.

Controllo accessi: i file di cartelle private o nascoste sono scaricabili
solo da un amministratore o da chi ha sbloccato quella cartella con la
password. Impedisce di raggiungere le foto di uno shooting privato
indovinando gli identificativi.
"""
import zipstream
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import FileResponse, Response, StreamingResponse

from ..config import get_settings
from ..database import get_db, record_stat
from ..deps import get_current_user
from ..thumbnails import (get_or_create_thumbnail, SIZE_SMALL,
                          SIZE_CARD, SIZE_MEDIUM, SIZE_COVER, SIZE_SOCIAL,
                          FORMATO_JPEG, FORMATO_WEBP, FORMATO_AVIF, TIPO_MIME)
from .tree import _is_unlocked, scaduto

router = APIRouter()


def _is_admin(request: Request) -> bool:
    u = get_current_user(request)
    return bool(u and u.get("is_admin"))


def _get_media(media_id: int):
    with get_db() as conn:
        row = conn.execute(
            "SELECT m.id, m.rel_path, m.filename, m.mtime, m.kind, m.node_id, "
            "n.downloads_enabled, n.is_private, n.hidden, n.expires_at, n.id AS nid "
            "FROM media m JOIN nodes n ON n.id=m.node_id WHERE m.id=?",
            (media_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Media non trovato")
    return row


def _can_access(request: Request, node_id: int, is_private: int, hidden: int,
                expires_at=None) -> bool:
    """Admin sempre; gli altri solo da cartelle pubbliche o gia' sbloccate,
    e mai da un link di condivisione scaduto."""
    if _is_admin(request):
        return True
    if hidden:
        return False
    if scaduto(expires_at):
        return False
    if is_private:
        return _is_unlocked(request, node_id)
    return True


def _formato_per(request: Request) -> str:
    """Formato migliore per questo browser.

    Tre gradini, dal piu' nuovo al piu' vecchio. L'AVIF pesa circa un terzo
    meno del WebP a parita' di resa, il WebP il 40% meno del JPEG. Ogni
    browser dichiara nell'intestazione Accept quali formati sa leggere: si
    serve il migliore fra quelli, e a chi non dichiara niente resta il
    JPEG, che aprono tutti.
    """
    accetta = request.headers.get("accept", "")
    if "image/avif" in accetta:
        return FORMATO_AVIF
    if "image/webp" in accetta:
        return FORMATO_WEBP
    return FORMATO_JPEG


def _serve_thumb(request: Request, media_id: int, size: str):
    """Le anteprime di cartelle private o nascoste sono servite solo a chi
    ha diritto di vederle: senza questo controllo basterebbe indovinare un
    identificativo per sfogliare uno shooting riservato."""
    m = _get_media(media_id)
    if not _can_access(request, m["nid"], m["is_private"], m["hidden"], m["expires_at"]):
        raise HTTPException(status_code=404, detail="Non disponibile")
    # L'anteprima social va sempre in JPEG: i programmi che leggono i
    # collegamenti nelle chat non dichiarano di sapere leggere il WebP e
    # alcuni non lo aprono affatto.
    formato = FORMATO_JPEG if size == SIZE_SOCIAL else _formato_per(request)
    thumb = get_or_create_thumbnail(m["rel_path"], m["mtime"], m["kind"],
                                    size, formato)
    if not thumb or not thumb.exists():
        # Se per qualche motivo il WebP non si e' potuto creare, si ripiega
        # sul JPEG invece di lasciare un riquadro vuoto.
        formato = FORMATO_JPEG
        thumb = get_or_create_thumbnail(m["rel_path"], m["mtime"], m["kind"],
                                        size, formato)
    if not thumb or not thumb.exists():
        raise HTTPException(status_code=404, detail="Miniatura non disponibile")
    return FileResponse(
        str(thumb), media_type=TIPO_MIME[formato],
        # Vary: la stessa richiesta puo' produrre due file diversi a seconda
        # del browser. Senza, una cache intermedia servirebbe il WebP anche
        # a chi non sa leggerlo.
        headers={"Cache-Control": "public, max-age=604800",
                 "Vary": "Accept"})


@router.get("/thumb/{media_id}")
def thumbnail(request: Request, media_id: int):
    return _serve_thumb(request, media_id, SIZE_SMALL)


@router.get("/thumb2x/{media_id}")
def thumbnail_2x(request: Request, media_id: int):
    """Versione doppia della miniatura, per schermi ad alta densita'."""
    return _serve_thumb(request, media_id, SIZE_CARD)


@router.get("/cover/{media_id}")
def copertina(request: Request, media_id: int):
    """Versione leggera per la prima immagine della pagina."""
    return _serve_thumb(request, media_id, SIZE_COVER)


@router.get("/social/{media_id}")
def social(request: Request, media_id: int):
    """Immagine mostrata quando il collegamento finisce in una chat.

    Formato fisso 1200x630 e peso contenuto. Prima si usava l'anteprima
    grande, da oltre mezzo megabyte: WhatsApp scarta le immagini troppo
    pesanti e il collegamento usciva senza fotografia.
    """
    return _serve_thumb(request, media_id, SIZE_SOCIAL)


@router.get("/preview/{media_id}")
def preview(request: Request, media_id: int):
    return _serve_thumb(request, media_id, SIZE_MEDIUM)


@router.get("/video/{media_id}")
def video(media_id: int, request: Request):
    settings = get_settings()
    m = _get_media(media_id)
    if m["kind"] != "video":
        raise HTTPException(status_code=404, detail="Non e un video")
    if not _can_access(request, m["nid"], m["is_private"], m["hidden"], m["expires_at"]):
        raise HTTPException(status_code=403, detail="Accesso non consentito")
    if settings.use_xaccel:
        return Response(status_code=200, headers={
            "X-Accel-Redirect": f"/_originals/{quote(m['rel_path'])}",
            "Content-Type": "video/mp4", "Accept-Ranges": "bytes"})
    source = settings.photo_root_path / m["rel_path"]
    if not source.exists():
        raise HTTPException(status_code=404, detail="Video non trovato")
    return FileResponse(str(source), media_type="video/mp4")


@router.get("/download/{media_id}")
def download(media_id: int, request: Request):
    settings = get_settings()
    m = _get_media(media_id)
    if not m["downloads_enabled"]:
        raise HTTPException(status_code=403, detail="Download disabilitato")
    # "Non esiste" e non "non ti e' permesso": rispondere in modo diverso a
    # seconda che la fotografia ci sia o no permetterebbe, provando gli
    # identificativi a uno a uno, di ricostruire quante e quali fotografie
    # contiene uno shooting riservato senza vederne nessuna. Le miniature e
    # le anteprime rispondono gia' cosi'.
    if not _can_access(request, m["nid"], m["is_private"], m["hidden"], m["expires_at"]):
        raise HTTPException(status_code=404, detail="Non disponibile")
    record_stat("download", m["rel_path"])
    disposition = f"attachment; filename*=UTF-8''{quote(m['filename'])}"
    if settings.use_xaccel:
        return Response(status_code=200, headers={
            "X-Accel-Redirect": f"/_originals/{quote(m['rel_path'])}",
            "Content-Disposition": disposition,
            "Content-Type": "application/octet-stream"})
    source = settings.photo_root_path / m["rel_path"]
    if not source.exists():
        raise HTTPException(status_code=404, detail="File non trovato")
    return FileResponse(str(source), media_type="application/octet-stream",
                        filename=m["filename"])


def _zip_stream(files):
    z = zipstream.ZipFile(mode="w", compression=zipstream.ZIP_STORED)
    for abs_path, arcname in files:
        z.write(str(abs_path), arcname=arcname)
    for chunk in z:
        yield chunk


@router.get("/zip/node/{node_id}")
def zip_node(node_id: int, request: Request):
    settings = get_settings()
    with get_db() as conn:
        node = conn.execute(
            "SELECT id, title, downloads_enabled, is_private, hidden, expires_at "
            "FROM nodes WHERE id=?", (node_id,)).fetchone()
        if not node:
            raise HTTPException(status_code=404, detail="Cartella non trovata")
        if not node["downloads_enabled"]:
            raise HTTPException(status_code=403, detail="Download disabilitato")
        if not _can_access(request, node["id"], node["is_private"], node["hidden"], node["expires_at"]):
            raise HTTPException(status_code=403, detail="Accesso non consentito")
        rows = conn.execute(
            "SELECT rel_path, filename FROM media WHERE node_id=? ORDER BY filename",
            (node_id,)).fetchall()
    files = []
    for r in rows:
        p = settings.photo_root_path / r["rel_path"]
        if p.exists():
            files.append((p, r["filename"]))
    if not files:
        raise HTTPException(status_code=404, detail="Nessun file da scaricare")
    record_stat("zip_node", str(node_id))
    zipname = quote(f"{node['title']}.zip")
    return StreamingResponse(_zip_stream(files), media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{zipname}"})


@router.get("/zip/select")
def zip_select(request: Request, ids: str = Query(...)):
    settings = get_settings()
    id_list = [int(x) for x in ids.split(",") if x.strip().isdigit()][:2000]
    if not id_list:
        raise HTTPException(status_code=400, detail="Selezione vuota")
    placeholders = ",".join("?" * len(id_list))
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT m.rel_path, m.filename, n.id AS nid, n.is_private, n.hidden, n.expires_at "
            f"FROM media m JOIN nodes n ON n.id=m.node_id "
            f"WHERE m.id IN ({placeholders}) AND n.downloads_enabled=1", id_list).fetchall()
    files = []
    for r in rows:
        if not _can_access(request, r["nid"], r["is_private"], r["hidden"], r["expires_at"]):
            continue
        p = settings.photo_root_path / r["rel_path"]
        if p.exists():
            files.append((p, r["filename"]))
    if not files:
        raise HTTPException(status_code=403, detail="Nessun file scaricabile")
    record_stat("zip_select", str(len(files)))
    return StreamingResponse(_zip_stream(files), media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename*=UTF-8''selezione.zip"})
