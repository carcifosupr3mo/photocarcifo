"""Calendario pubblico dei raduni.

Pagina pubblica, raggiungibile dalla barra di navigazione e indicizzabile:
mostra gli appuntamenti e, sotto ciascuno, gli album fotografici collegati
(quelli gia' pubblici nel resto del sito: la pagina non aggiunge un
secondo modo per vedere cio' che e' privato o nascosto).
"""
from datetime import datetime
from urllib.parse import urlparse

from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from ..database import get_db, get_setting, set_setting, log_event
from ..deps import get_current_user, require_admin_user, require_admin_api
from ..security import verify_csrf
from ..templating import templates

router = APIRouter()

# Servizi di mappe accettati per il collegamento al luogo.
DOMINI_MAPPE = (
    "google.com", "google.ch", "google.it", "maps.google.com",
    "maps.app.goo.gl", "goo.gl", "openstreetmap.org", "osm.org",
    "maps.apple.com", "waze.com",
)


def mappa_valida(url: str) -> bool:
    """Accetta solo indirizzi di servizi di mappe conosciuti.

    Il controllo avviene sul dominio vero e non sul testo: un indirizzo
    come evil.com/google.com/maps viene respinto."""
    if not url or not url.strip():
        return True
    try:
        p = urlparse(url.strip())
    except ValueError:
        return False
    if p.scheme != "https" or not p.netloc:
        return False
    host = p.netloc.lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return any(host == d or host.endswith("." + d) for d in DOMINI_MAPPE)


def _avviso() -> str:
    return get_setting(
        "raduni_avviso",
        "Non sono organizzatore ne' affiliato ai raduni elencati. "
        "Partecipo esclusivamente come fotografo per documentare gli eventi. "
        "Ogni partecipante e' responsabile della propria condotta e del "
        "rispetto del codice della strada.")


def _prossimi():
    with get_db() as conn:
        righe = conn.execute(
            "SELECT id, data, ora, luogo, note, mappa FROM raduni "
            "WHERE data >= date('now') ORDER BY data, ora").fetchall()
    return [dict(r) for r in righe]


def _passati():
    with get_db() as conn:
        righe = conn.execute(
            "SELECT id, data, ora, luogo, note, mappa FROM raduni "
            "WHERE data < date('now') ORDER BY data DESC LIMIT 12").fetchall()
    return [dict(r) for r in righe]


def _album_pubblici(raduno_id: int) -> list:
    """Album collegati a un raduno, filtrati con le stesse regole di
    visibilita' pubblica usate nel resto del sito (tree.py): niente
    privati, niente nascosti, niente scaduti. Collegare un album a un
    raduno non gli cambia la visibilita'."""
    from .tree import scaduto
    with get_db() as conn:
        righe = conn.execute(
            "SELECT n.id, n.slug, n.title, n.cover_media_id, n.total_media, "
            "n.expires_at "
            "FROM raduni_albums ra JOIN nodes n ON n.id = ra.node_id "
            "WHERE ra.raduno_id=? AND n.is_private=0 AND n.hidden=0 "
            "ORDER BY ra.sort_order, n.title", (raduno_id,)).fetchall()
        righe = [dict(r) for r in righe if not scaduto(r["expires_at"])]
        ids = [r["id"] for r in righe]
        copertine = {}
        if ids:
            segnaposto = ",".join("?" * len(ids))
            for r in conn.execute(
                f"SELECT id, rel_path FROM media WHERE id IN "
                f"(SELECT cover_media_id FROM nodes WHERE id IN ({segnaposto}))",
                ids):
                copertine[r["id"]] = r["rel_path"]
        for r in righe:
            r["cover"] = copertine.get(r["cover_media_id"])
        return righe


def _album_admin(raduno_id: int) -> list:
    """Come sopra ma senza filtro di visibilita': serve al pannello, dove
    un admin deve poter vedere anche un album privato o nascosto gia'
    collegato (e capire che al pubblico non comparira')."""
    with get_db() as conn:
        righe = conn.execute(
            "SELECT n.id, n.slug, n.title, n.total_media, n.is_private, n.hidden "
            "FROM raduni_albums ra JOIN nodes n ON n.id = ra.node_id "
            "WHERE ra.raduno_id=? ORDER BY ra.sort_order, n.title",
            (raduno_id,)).fetchall()
        return [dict(r) for r in righe]


@router.get("/radunimoto", response_class=HTMLResponse)
def pagina(request: Request):
    prossimi = _prossimi()
    passati = _passati()
    for r in prossimi:
        r["album"] = _album_pubblici(r["id"])
    for r in passati:
        r["album"] = _album_pubblici(r["id"])
    return templates.TemplateResponse(request, "public/raduni.html", {"avviso": _avviso(),
        "prossimi": prossimi, "passati": passati,
        "is_admin": bool((get_current_user(request) or {}).get("is_admin"))})


@router.get("/admin/raduni", response_class=HTMLResponse)
def admin_pagina(request: Request, user: dict = Depends(require_admin_user)):
    with get_db() as conn:
        righe = conn.execute(
            "SELECT id, data, ora, luogo, note, mappa FROM raduni "
            "ORDER BY data DESC").fetchall()
    raduni = [dict(r) for r in righe]
    for r in raduni:
        r["album"] = _album_admin(r["id"])
    return templates.TemplateResponse(request, "admin/raduni.html", {"user": user, "raduni": raduni,
        "avviso": _avviso()})


@router.post("/admin/raduni/avviso")
def salva_avviso(csrf_token: str = Form(...), avviso: str = Form(""),
                 user: dict = Depends(require_admin_api)):
    if not verify_csrf(user.get("csrf", ""), csrf_token):
        raise HTTPException(status_code=403, detail="Sessione non valida")
    set_setting("raduni_avviso", avviso.strip()[:1500])
    return JSONResponse({"ok": True})


@router.post("/admin/raduni/aggiungi")
def aggiungi(csrf_token: str = Form(...), data: str = Form(...),
             ora: str = Form(""), luogo: str = Form(...), note: str = Form(""),
             mappa: str = Form(""),
             user: dict = Depends(require_admin_api)):
    if not verify_csrf(user.get("csrf", ""), csrf_token):
        raise HTTPException(status_code=403, detail="Sessione non valida")
    try:
        datetime.strptime(data, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Data non valida")
    if not mappa_valida(mappa):
        raise HTTPException(
            status_code=400,
            detail="Collegamento non valido: usa un indirizzo di Google Maps, "
                   "Apple Maps, OpenStreetMap o Waze che inizi con https://")
    with get_db() as conn:
        conn.execute(
            "INSERT INTO raduni(data, ora, luogo, note, mappa, creato) "
            "VALUES(?,?,?,?,?,datetime('now'))",
            (data, ora.strip()[:20], luogo.strip()[:200], note.strip()[:500],
             mappa.strip()[:500] or None))
    log_event("INFO", "raduni", f"Aggiunto raduno del {data}")
    return JSONResponse({"ok": True})


@router.post("/admin/raduni/{raduno_id}/elimina")
def elimina(raduno_id: int, csrf_token: str = Form(...),
            user: dict = Depends(require_admin_api)):
    if not verify_csrf(user.get("csrf", ""), csrf_token):
        raise HTTPException(status_code=403, detail="Sessione non valida")
    with get_db() as conn:
        # Le associazioni in raduni_albums hanno FK ON DELETE CASCADE:
        # spariscono con il raduno, gli album (nodes) restano intatti.
        conn.execute("DELETE FROM raduni WHERE id=?", (raduno_id,))
    return JSONResponse({"ok": True})


@router.post("/admin/raduni/{raduno_id}/mappa")
def modifica_mappa(raduno_id: int, csrf_token: str = Form(...),
                   mappa: str = Form(""),
                   user: dict = Depends(require_admin_api)):
    """Aggiunge o cambia il collegamento alle mappe di un appuntamento."""
    if not verify_csrf(user.get("csrf", ""), csrf_token):
        raise HTTPException(status_code=403, detail="Sessione non valida")
    if not mappa_valida(mappa):
        raise HTTPException(
            status_code=400,
            detail="Collegamento non valido: usa Google Maps, Apple Maps, "
                   "OpenStreetMap o Waze, con indirizzo che inizia per https://")
    with get_db() as conn:
        conn.execute("UPDATE raduni SET mappa=? WHERE id=?",
                     (mappa.strip()[:500] or None, raduno_id))
    return JSONResponse({"ok": True})


@router.post("/admin/raduni/{raduno_id}/album/collega")
def collega_album(raduno_id: int, csrf_token: str = Form(...),
                  node_id: int = Form(...),
                  user: dict = Depends(require_admin_api)):
    """Collega un album esistente al raduno. Non tocca il nodo: nessuna
    copia, nessuno spostamento, nessun cambio di categoria/slug/URL."""
    if not verify_csrf(user.get("csrf", ""), csrf_token):
        raise HTTPException(status_code=403, detail="Sessione non valida")
    with get_db() as conn:
        esiste = conn.execute("SELECT id FROM nodes WHERE id=?", (node_id,)).fetchone()
        if not esiste:
            raise HTTPException(status_code=404, detail="Album non trovato")
        ordine = conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 AS n FROM raduni_albums "
            "WHERE raduno_id=?", (raduno_id,)).fetchone()["n"]
        conn.execute(
            "INSERT OR IGNORE INTO raduni_albums(raduno_id, node_id, sort_order, creato) "
            "VALUES(?,?,?,datetime('now'))", (raduno_id, node_id, ordine))
    log_event("INFO", "raduni", f"Album {node_id} collegato al raduno {raduno_id}")
    return JSONResponse({"ok": True})


@router.post("/admin/raduni/{raduno_id}/album/{node_id}/rimuovi")
def scollega_album(raduno_id: int, node_id: int, csrf_token: str = Form(...),
                   user: dict = Depends(require_admin_api)):
    """Rimuove SOLO l'associazione raduno-album: l'album (nodo, foto,
    file sul NAS) non viene toccato in alcun modo, resta esattamente dove
    e' sempre stato, raggiungibile dalla sua categoria come prima."""
    if not verify_csrf(user.get("csrf", ""), csrf_token):
        raise HTTPException(status_code=403, detail="Sessione non valida")
    with get_db() as conn:
        conn.execute("DELETE FROM raduni_albums WHERE raduno_id=? AND node_id=?",
                     (raduno_id, node_id))
    log_event("INFO", "raduni", f"Album {node_id} rimosso dal raduno {raduno_id}")
    return JSONResponse({"ok": True})
