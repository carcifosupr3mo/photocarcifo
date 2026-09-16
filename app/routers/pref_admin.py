"""Pagina del pannello con tutte le fotografie scelte dai clienti."""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse

from ..database import get_db
from ..deps import require_admin_user
from ..templating import templates

router = APIRouter(prefix="/admin/preferite")


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def pagina(request: Request, user: dict = Depends(require_admin_user)):
    """Elenco degli album in cui qualcuno ha segnato delle fotografie."""
    with get_db() as conn:
        righe = conn.execute(
            "SELECT n.id, n.title, n.rel_path, n.slug, n.is_private, n.access_token, "
            "       COUNT(p.id) AS quante, "
            "       COUNT(DISTINCT p.ospite) AS persone, "
            "       MAX(p.ts) AS ultima "
            "FROM preferiti p JOIN nodes n ON n.id = p.node_id "
            "GROUP BY n.id ORDER BY ultima DESC").fetchall()
        totale = conn.execute("SELECT COUNT(*) c FROM preferiti").fetchone()["c"]
        clienti = conn.execute(
            "SELECT COUNT(DISTINCT ospite) c FROM preferiti").fetchone()["c"]
    album = []
    with get_db() as conn:
        for r in righe:
            d = dict(r)
            d["percorso"] = r["rel_path"].replace("_", " ").replace("/", " / ")
            d["ultima_data"] = (r["ultima"] or "")[:10]
            # prime sei fotografie scelte, per l'anteprima nella scheda
            d["anteprime"] = [x["media_id"] for x in conn.execute(
                "SELECT DISTINCT media_id FROM preferiti WHERE node_id=? "
                "ORDER BY ts DESC LIMIT 6", (r["id"],)).fetchall()]
            album.append(d)
    return templates.TemplateResponse(request, "admin/preferite.html", {"user": user, "album": album,
        "totale": totale, "clienti": clienti})
