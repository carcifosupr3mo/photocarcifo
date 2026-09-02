"""Preferiti: il cliente segna le fotografie che vuole.

Ogni visitatore di un album puo' contrassegnare le fotografie che
preferisce. Le scelte sono legate a un identificativo casuale conservato
nel browser, quindi non serve alcuna registrazione. Il fotografo vede
l'elenco completo dal pannello.
"""
import re
import secrets

from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import JSONResponse

from ..database import get_db
from ..deps import get_current_user, require_admin_api
from ..templating import templates
from ..security import verify_csrf

router = APIRouter()

COOKIE_OSPITE = "pc_ospite"
COOKIE_NOME = "pc_nome"

# Regola ufficiale di Instagram: lettere, numeri, punto e trattino basso,
# da 1 a 30 caratteri, senza punti doppi o finali.
_RE_INSTAGRAM = re.compile(r"^(?!.*\.\.)[A-Za-z0-9._]{1,30}$")


def pulisci_instagram(valore: str) -> str:
    """Ricava il nome utente da quello che ha scritto la persona.

    Accetta anche un indirizzo completo o un nome preceduto da chiocciola,
    perche' e' quello che la gente incolla piu' spesso."""
    v = (valore or "").strip()
    v = re.sub(r"^https?://(www\.)?instagram\.com/", "", v, flags=re.I)
    v = v.split("?")[0].strip("/@ ").strip()
    return v


def instagram_valido(nome: str) -> bool:
    if not nome or nome.endswith(".") or nome.startswith("."):
        return False
    return bool(_RE_INSTAGRAM.match(nome))


def nome_valido(nome: str) -> bool:
    """Nome e cognome di chi non usa Instagram: almeno due caratteri,
    solo lettere, spazi e apostrofi."""
    n = (nome or "").strip()
    if len(n) < 2 or len(n) > 60:
        return False
    return bool(re.match(r"^[A-Za-zÀ-ÿ' ]+$", n))
MAX_PREFERITI = 500


def _ospite(request: Request) -> str:
    """Identificativo casuale del visitatore, conservato nel browser."""
    return request.cookies.get(COOKIE_OSPITE, "")


def _nuovo_ospite() -> str:
    return secrets.token_urlsafe(16)


def _puo_vedere(request: Request, node_id: int) -> bool:
    """Solo chi ha accesso all'album puo' segnare le sue fotografie."""
    from .tree import _is_unlocked, scaduto
    u = get_current_user(request)
    if u and u.get("is_admin"):
        return True
    with get_db() as conn:
        n = conn.execute(
            "SELECT is_private, hidden, expires_at FROM nodes WHERE id=?",
            (node_id,)).fetchone()
    if not n or n["hidden"]:
        return False
    if scaduto(n["expires_at"]):
        return False
    if n["is_private"]:
        return _is_unlocked(request, node_id)
    return True


@router.post("/preferiti/{media_id}")
def segna(request: Request, media_id: int):
    """Aggiunge o toglie una fotografia dai preferiti del visitatore."""
    with get_db() as conn:
        m = conn.execute("SELECT node_id FROM media WHERE id=?", (media_id,)).fetchone()
    if not m:
        raise HTTPException(status_code=404, detail="Fotografia non trovata")
    if not _puo_vedere(request, m["node_id"]):
        raise HTTPException(status_code=403, detail="Accesso non consentito")

    ospite = _ospite(request)
    nuovo = not ospite
    if nuovo:
        ospite = _nuovo_ospite()

    with get_db() as conn:
        gia = conn.execute(
            "SELECT id FROM preferiti WHERE ospite=? AND media_id=?",
            (ospite, media_id)).fetchone()
        if gia:
            conn.execute("DELETE FROM preferiti WHERE id=?", (gia["id"],))
            attivo = False
        else:
            quanti = conn.execute(
                "SELECT COUNT(*) c FROM preferiti WHERE ospite=?",
                (ospite,)).fetchone()["c"]
            if quanti >= MAX_PREFERITI:
                raise HTTPException(status_code=429,
                                    detail="Hai raggiunto il limite di preferiti")
            nome = request.cookies.get(COOKIE_NOME, "")
            conn.execute(
                "INSERT INTO preferiti(ospite, media_id, node_id, ts, instagram) "
                "VALUES(?,?,?,datetime('now'),?)",
                (ospite, media_id, m["node_id"], nome or None))
            attivo = True
        totale = conn.execute(
            "SELECT COUNT(*) c FROM preferiti WHERE ospite=? AND node_id=?",
            (ospite, m["node_id"])).fetchone()["c"]

    risposta = JSONResponse({"ok": True, "attivo": attivo, "totale": totale})
    if nuovo:
        risposta.set_cookie(COOKIE_OSPITE, ospite, max_age=60 * 60 * 24 * 365,
                            httponly=True, samesite="lax", secure=True, path="/")
    return risposta


@router.get("/preferiti/album/{node_id}")
def elenco(request: Request, node_id: int):
    """Identificativi delle fotografie gia' segnate dal visitatore."""
    ospite = _ospite(request)
    if not ospite or not _puo_vedere(request, node_id):
        return JSONResponse({"ids": [], "totale": 0})
    with get_db() as conn:
        righe = conn.execute(
            "SELECT media_id FROM preferiti WHERE ospite=? AND node_id=?",
            (ospite, node_id)).fetchall()
    ids = [r["media_id"] for r in righe]
    return JSONResponse({"ids": ids, "totale": len(ids)})


@router.get("/admin/preferiti/{node_id}")
def preferiti_admin(node_id: int, user: dict = Depends(require_admin_api)):
    """Raggruppa per visitatore le fotografie scelte in un album."""
    with get_db() as conn:
        righe = conn.execute(
            "SELECT p.ospite, p.media_id, p.ts, p.instagram, m.filename "
            "FROM preferiti p JOIN media m ON m.id = p.media_id "
            "WHERE p.node_id=? ORDER BY p.ospite, p.ts", (node_id,)).fetchall()
    persone = {}
    for r in righe:
        v = persone.setdefault(r["ospite"], {
            "quante": 0, "dal": r["ts"], "instagram": "", "foto": []})
        v["quante"] += 1
        if r["instagram"]:
            v["instagram"] = r["instagram"]
        v["foto"].append({"id": r["media_id"], "nome": r["filename"]})
    elenco_persone = [
        {"codice": k[:8], "quante": v["quante"], "dal": v["dal"],
         "instagram": v.get("instagram") or "",
         "ids": [f["id"] for f in v["foto"]],
         "nomi": [f["nome"] for f in v["foto"]]}
        for k, v in persone.items()]
    elenco_persone.sort(key=lambda x: -x["quante"])
    return JSONResponse({"persone": elenco_persone, "totale": len(righe)})


@router.post("/admin/preferiti/{node_id}/rimuovi")
def rimuovi_admin(node_id: int, csrf_token: str = Form(...),
                  ospite: str = Form(""), media_id: str = Form(""),
                  user: dict = Depends(require_admin_api)):
    """Toglie preferenze: una singola fotografia, un cliente, o tutto l'album."""
    if not verify_csrf(user.get("csrf", ""), csrf_token):
        raise HTTPException(status_code=403, detail="Sessione non valida")
    # Il pannello manda solo le prime 8 lettere del codice cliente, quindi si
    # confronta quel pezzo. Non si usa LIKE: i codici sono generati con
    # token_urlsafe e possono contenere "_", che per LIKE e' un carattere
    # jolly. Cancellando le preferite di un cliente si rischiava di
    # cancellare anche quelle di un altro.
    with get_db() as conn:
        if media_id and ospite:
            conn.execute("DELETE FROM preferiti WHERE node_id=? AND media_id=? "
                         "AND substr(ospite, 1, ?)=?",
                         (node_id, int(media_id), len(ospite), ospite))
        elif ospite:
            conn.execute("DELETE FROM preferiti WHERE node_id=? "
                         "AND substr(ospite, 1, ?)=?",
                         (node_id, len(ospite), ospite))
        else:
            conn.execute("DELETE FROM preferiti WHERE node_id=?", (node_id,))
        restano = conn.execute("SELECT COUNT(*) c FROM preferiti WHERE node_id=?",
                               (node_id,)).fetchone()["c"]
    return JSONResponse({"ok": True, "restano": restano})


@router.post("/preferiti-nome")
def registra_nome(request: Request, instagram: str = Form(""),
                  nome_persona: str = Form(""), tipo: str = Form("ig")):
    """Registra chi sta scegliendo le fotografie: profilo Instagram
    oppure nome e cognome per chi non lo usa."""
    if tipo == "nome":
        nome = (nome_persona or "").strip()
        if not nome_valido(nome):
            raise HTTPException(
                status_code=400,
                detail="Scrivi nome e cognome, solo lettere.")
        nome = "nome:" + nome
    else:
        nome = pulisci_instagram(instagram)
        if not instagram_valido(nome):
            raise HTTPException(
                status_code=400,
                detail="Nome non valido: usa solo lettere, numeri, punto e trattino basso.")

    ospite = _ospite(request)
    nuovo = not ospite
    if nuovo:
        ospite = _nuovo_ospite()

    with get_db() as conn:
        conn.execute("UPDATE preferiti SET instagram=? WHERE ospite=?", (nome, ospite))

    risposta = JSONResponse({"ok": True, "instagram": nome})
    if nuovo:
        risposta.set_cookie(COOKIE_OSPITE, ospite, max_age=60 * 60 * 24 * 365,
                            httponly=True, samesite="lax", secure=True, path="/")
    risposta.set_cookie(COOKIE_NOME, nome, max_age=60 * 60 * 24 * 365,
                        samesite="lax", secure=True, path="/")
    return risposta


@router.get("/mie-preferite")
def mie_preferite(request: Request):
    """Pagina personale: tutte le fotografie che il visitatore ha segnato."""
    ospite = _ospite(request)
    if not ospite:
        return templates.TemplateResponse(request, "public/mie_preferite.html", {"album": [], "totale": 0, "nome": ""})
    with get_db() as conn:
        righe = conn.execute(
            "SELECT p.media_id, p.node_id, p.ts, p.instagram, "
            "       n.title, n.slug, n.is_private, n.access_token "
            "FROM preferiti p JOIN nodes n ON n.id = p.node_id "
            "WHERE p.ospite=? ORDER BY p.ts DESC", (ospite,)).fetchall()
    per_album = {}
    nome = ""
    for r in righe:
        if r["instagram"]:
            nome = r["instagram"]
        chiave = r["node_id"]
        v = per_album.setdefault(chiave, {
            "titolo": r["title"], "slug": r["slug"],
            "is_private": r["is_private"], "token": r["access_token"], "foto": []})
        v["foto"].append(r["media_id"])
    album = list(per_album.values())
    return templates.TemplateResponse(request, "public/mie_preferite.html", {"album": album, "totale": len(righe),
        "nome": nome})
