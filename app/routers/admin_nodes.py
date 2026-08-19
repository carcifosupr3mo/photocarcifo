"""Gestione amministrativa ad albero espandibile."""
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from ..database import get_db, log_event, sottoalbero_like
from ..deps import require_admin_user, require_admin_api
from ..security import hash_password, verify_csrf, generate_access_token
from ..templating import templates

router = APIRouter(prefix="/admin/tree")


def _check_csrf(user, tok):
    if not verify_csrf(user.get("csrf", ""), tok):
        raise HTTPException(status_code=403, detail="CSRF non valido")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _has_children(conn, node_id):
    return conn.execute("SELECT 1 FROM nodes WHERE parent_id=? LIMIT 1", (node_id,)).fetchone() is not None


def _cover_id(conn, r):
    """Id della foto di copertina: personalizzata o prima immagine del sottoalbero."""
    if r["cover_media_id"]:
        return r["cover_media_id"]
    row = conn.execute(
        "SELECT m.id FROM media m JOIN nodes n ON n.id=m.node_id "
        "WHERE (n.rel_path=? OR n.rel_path LIKE ? ESCAPE '\\') AND m.kind='image' "
        "ORDER BY m.filename LIMIT 1",
        (r["rel_path"], sottoalbero_like(r["rel_path"]))).fetchone()
    return row["id"] if row else None


def _serialize(conn, r):
    return {
        "id": r["id"], "title": r["title"], "name": r["name"],
        "slug": r["slug"],
        "cover": _cover_id(conn, r),
        "is_private": bool(r["is_private"]), "hidden": bool(r["hidden"]),
        "downloads_enabled": bool(r["downloads_enabled"]),
        "has_password": bool(r["password_hash"]),
        "access_token": r["access_token"], "total_media": r["total_media"],
        "direct_media": r["direct_media"], "depth": r["depth"],
        "has_children": _has_children(conn, r["id"]),
    }


@router.get("", response_class=HTMLResponse)
def tree_page(request: Request, user: dict = Depends(require_admin_user)):
    return templates.TemplateResponse(request, "admin/tree.html", {"user": user})


@router.get("/api/children")
def api_children(request: Request, parent: str = "", user: dict = Depends(require_admin_user)):
    with get_db() as conn:
        if parent in ("", "0", "root"):
            rows = conn.execute("SELECT * FROM nodes WHERE parent_id IS NULL ORDER BY sort_order, title").fetchall()
        else:
            rows = conn.execute("SELECT * FROM nodes WHERE parent_id=? ORDER BY sort_order, title", (int(parent),)).fetchall()
        return JSONResponse([_serialize(conn, r) for r in rows])


@router.get("/api/node")
def api_node(request: Request, id: int, user: dict = Depends(require_admin_user)):
    with get_db() as conn:
        r = conn.execute("SELECT * FROM nodes WHERE id=?", (id,)).fetchone()
        if not r:
            raise HTTPException(status_code=404, detail="Nodo non trovato")
        d = _serialize(conn, r)
        d["rel_path"] = r["rel_path"]
        from ..config import get_settings
        d["site_url"] = get_settings().site_url.rstrip("/")
        from .tree import giorni_rimasti, scaduto
        d["expires_at"] = r["expires_at"]
        d["giorni_rimasti"] = giorni_rimasti(r["expires_at"])
        d["scaduto"] = scaduto(r["expires_at"])
        return JSONResponse(d)


@router.post("/{node_id}/rename")
def rename(request: Request, node_id: int, csrf_token: str = Form(...),
           title: str = Form(...), user: dict = Depends(require_admin_api)):
    _check_csrf(user, csrf_token)
    t = title.strip() or "(senza titolo)"
    with get_db() as conn:
        conn.execute("UPDATE nodes SET title=?, updated_at=? WHERE id=?", (t, _now(), node_id))
    log_event("INFO", "admin", f"Rinominato nodo {node_id} -> '{t}'")
    return JSONResponse({"ok": True, "title": t})


@router.post("/{node_id}/hide")
def hide(request: Request, node_id: int, csrf_token: str = Form(...),
         hidden: str = Form("0"), user: dict = Depends(require_admin_api)):
    _check_csrf(user, csrf_token)
    h = 1 if hidden == "1" else 0
    with get_db() as conn:
        node = conn.execute("SELECT rel_path FROM nodes WHERE id=?", (node_id,)).fetchone()
        if not node:
            raise HTTPException(status_code=404, detail="Nodo non trovato")
        conn.execute("UPDATE nodes SET hidden=?, updated_at=? WHERE id=?", (h, _now(), node_id))
        conn.execute("UPDATE nodes SET hidden=? WHERE rel_path LIKE ? ESCAPE '\\'",
                     (h, sottoalbero_like(node["rel_path"])))
    return JSONResponse({"ok": True, "hidden": bool(h)})


@router.post("/{node_id}/privacy")
def privacy(request: Request, node_id: int, csrf_token: str = Form(...),
            is_private: str = Form("0"), user: dict = Depends(require_admin_api)):
    _check_csrf(user, csrf_token)
    private = 1 if is_private == "1" else 0
    with get_db() as conn:
        node = conn.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
        if not node:
            raise HTTPException(status_code=404, detail="Nodo non trovato")
        token = node["access_token"] or (generate_access_token() if private else None)
        conn.execute("UPDATE nodes SET is_private=?, access_token=?, updated_at=? WHERE id=?",
                     (private, token if private else None, _now(), node_id))
        conn.execute("UPDATE nodes SET is_private=? WHERE rel_path LIKE ? ESCAPE '\\'",
                     (private, sottoalbero_like(node["rel_path"])))
        # Le sottocartelle diventano private insieme alla madre, ma finora
        # restavano senza link proprio: chi apriva una di quelle dal pannello
        # finiva su "/p/None", perche' il modello scriveva nell'indirizzo il
        # nulla che trovava. Un album privato senza link e' un album che non
        # si puo' aprire in nessun modo, nemmeno da chi lo possiede.
        if private:
            orfani = conn.execute(
                "SELECT id FROM nodes WHERE rel_path LIKE ? ESCAPE '\\' "
                "AND is_private=1 AND (access_token IS NULL OR access_token='')",
                (sottoalbero_like(node["rel_path"]),)).fetchall()
            for o in orfani:
                conn.execute("UPDATE nodes SET access_token=?, updated_at=? WHERE id=?",
                             (generate_access_token(), _now(), o["id"]))
    return JSONResponse({"ok": True, "is_private": bool(private), "access_token": token if private else None})


@router.post("/{node_id}/regen-link")
def regen_link(request: Request, node_id: int, csrf_token: str = Form(...),
               user: dict = Depends(require_admin_api)):
    _check_csrf(user, csrf_token)
    tok = generate_access_token()
    with get_db() as conn:
        conn.execute("UPDATE nodes SET access_token=?, updated_at=? WHERE id=?", (tok, _now(), node_id))
    return JSONResponse({"ok": True, "access_token": tok})


@router.post("/{node_id}/password")
def password(request: Request, node_id: int, csrf_token: str = Form(...),
             password: str = Form(""), clear: str = Form("0"),
             user: dict = Depends(require_admin_api)):
    _check_csrf(user, csrf_token)
    with get_db() as conn:
        if clear == "1":
            conn.execute("UPDATE nodes SET password_hash=NULL, updated_at=? WHERE id=?", (_now(), node_id))
            return JSONResponse({"ok": True, "has_password": False})
        elif password.strip():
            conn.execute("UPDATE nodes SET password_hash=?, updated_at=? WHERE id=?",
                         (hash_password(password.strip()), _now(), node_id))
            return JSONResponse({"ok": True, "has_password": True})
    return JSONResponse({"ok": False})


@router.post("/{node_id}/downloads")
def downloads(request: Request, node_id: int, csrf_token: str = Form(...),
              downloads_enabled: str = Form("0"), user: dict = Depends(require_admin_api)):
    _check_csrf(user, csrf_token)
    en = 1 if downloads_enabled == "1" else 0
    with get_db() as conn:
        conn.execute("UPDATE nodes SET downloads_enabled=?, updated_at=? WHERE id=?", (en, _now(), node_id))
    return JSONResponse({"ok": True, "downloads_enabled": bool(en)})


@router.post("/{node_id}/scadenza")
def imposta_scadenza(node_id: int, csrf_token: str = Form(...),
                     giorni: str = Form("0"),
                     user: dict = Depends(require_admin_api)):
    """Imposta o toglie la scadenza del link di condivisione."""
    _check_csrf(user, csrf_token)
    from .tree import calcola_scadenza
    valore = calcola_scadenza(giorni)
    with get_db() as conn:
        conn.execute("UPDATE nodes SET expires_at=? WHERE id=?", (valore, node_id))
    log_event("INFO", "share",
              f"Scadenza link nodo {node_id}: " + (valore[:10] if valore else "illimitata"))
    return JSONResponse({"ok": True, "expires_at": valore})
