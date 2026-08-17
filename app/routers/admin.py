"""Dashboard amministratore - versione base compatibile col modello ad albero."""
import shutil

from fastapi import APIRouter, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import numeri, ocr
from ..database import get_db, log_event
from ..config import get_settings
from ..deps import require_admin_user, require_admin_api
from ..security import verify_csrf
from ..scanner import scan
from ..thumbnails import clear_cache
from ..templating import templates

router = APIRouter(prefix="/admin")


def _check_csrf(user, tok):
    if not verify_csrf(user.get("csrf", ""), tok):
        raise HTTPException(status_code=403, detail="CSRF non valido")


@router.get("", response_class=HTMLResponse)
def dashboard(request: Request, user: dict = Depends(require_admin_user)):
    settings = get_settings()
    with get_db() as conn:
        n_nodes = conn.execute("SELECT COUNT(*) c FROM nodes").fetchone()["c"]
        n_priv = conn.execute("SELECT COUNT(*) c FROM nodes WHERE is_private=1").fetchone()["c"]
        n_img = conn.execute("SELECT COUNT(*) c FROM media WHERE kind='image'").fetchone()["c"]
        n_vid = conn.execute("SELECT COUNT(*) c FROM media WHERE kind='video'").fetchone()["c"]
        visite_30gg = conn.execute(
            "SELECT COUNT(*) c FROM stats WHERE event='view_node' "
            "AND ts > datetime('now','-30 days')").fetchone()["c"]
        download_30gg = conn.execute(
            "SELECT COUNT(*) c FROM stats WHERE event IN ('download','zip_node','zip_select') "
            "AND ts > datetime('now','-30 days')").fetchone()["c"]
        piu_visti = conn.execute(
            "SELECT s.ref AS slug, n.title, COUNT(*) AS visite "
            "FROM stats s LEFT JOIN nodes n ON n.slug = s.ref "
            "WHERE s.event='view_node' AND s.ts > datetime('now','-30 days') "
            "GROUP BY s.ref ORDER BY visite DESC LIMIT 8").fetchall()
        conta_numeri = numeri.conteggi(conn)
    disk = {"total": 0, "used": 0, "free": 0}
    try:
        u = shutil.disk_usage(str(settings.photo_root_path))
        disk = {"total": u.total, "used": u.used, "free": u.free}
    except Exception:
        pass
    nas_ok = settings.photo_root_path.exists()
    return templates.TemplateResponse(request, "admin/dashboard.html", {"user": user,
        "stats": {"nodes": n_nodes, "private": n_priv, "images": n_img, "videos": n_vid,
                  "visite": visite_30gg, "download": download_30gg},
        "disk": disk, "nas_ok": nas_ok,
        "piu_visti": [dict(r) for r in piu_visti],
        "numeri": conta_numeri,
        "ocr_motore": ocr.motore_installato(),
        "ocr_processi": ocr.processi_consigliati(),
        "ocr_lavoro": ocr.stato_lavoro()})


# ---------------- Numeri di gara ----------------
@router.post("/maintenance/numeri")
def avvia_numeri(request: Request, csrf_token: str = Form(...),
                 user: dict = Depends(require_admin_api)):
    """Fa partire la lettura dei numeri sulle foto ancora in coda.

    Gira in sottofondo su piu' processi: su decine di migliaia di foto ci
    vuole parecchio e la pagina non deve restare appesa.
    """
    _check_csrf(user, csrf_token)
    if not ocr.disponibile():
        raise HTTPException(status_code=400,
                            detail="Nessun motore OCR installato sul server")
    avviata = ocr.avvia_in_sottofondo()
    log_event("INFO", "admin",
              f"Lettura numeri {'avviata' if avviata else 'gia in corso'}")
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/maintenance/numeri-reset")
def azzera_numeri(request: Request, csrf_token: str = Form(...),
                  user: dict = Depends(require_admin_api)):
    """Rimette in coda tutte le foto scartando i numeri letti automaticamente.

    Serve dopo aver cambiato le soglie di riconoscimento nel file .env.
    I numeri scritti a mano non si toccano.
    """
    _check_csrf(user, csrf_token)
    with get_db() as conn:
        numeri.azzera_ocr(conn)
    log_event("INFO", "admin", "Lettura numeri azzerata")
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/numeri/{node_id}", response_class=HTMLResponse)
def numeri_cartella(request: Request, node_id: int, pagina: int = 1,
                    user: dict = Depends(require_admin_user)):
    """Correzione a mano dei numeri delle foto di una cartella."""
    per_pagina = 120
    pagina = max(1, pagina)
    with get_db() as conn:
        node = conn.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
        if not node:
            raise HTTPException(status_code=404, detail="Cartella non trovata")
        totale = conn.execute("SELECT COUNT(*) c FROM media WHERE node_id=? "
                              "AND kind='image'", (node_id,)).fetchone()["c"]
        righe = conn.execute(
            "SELECT id, filename, ocr_stato FROM media WHERE node_id=? AND kind='image' "
            "ORDER BY sort_order, filename LIMIT ? OFFSET ?",
            (node_id, per_pagina, (pagina - 1) * per_pagina)).fetchall()
        foto = [dict(r) for r in righe]
        etichette = numeri.numeri_di(conn, [f["id"] for f in foto])

    for f in foto:
        f["numeri"] = ", ".join(etichette.get(f["id"], []))

    return templates.TemplateResponse(request, "admin/numeri.html", {"user": user, "node": dict(node), "foto": foto,
        "pagina": pagina, "pagine": max(1, (totale + per_pagina - 1) // per_pagina),
        "totale": totale, "ocr_motore": ocr.motore_installato()})


@router.post("/numeri/{node_id}")
async def salva_numeri(request: Request, node_id: int,
                       user: dict = Depends(require_admin_api)):
    """Salva i numeri corretti a mano.

    Il modulo ha un campo per ogni foto (`numero_<id>`), quindi si legge la
    richiesta grezza invece di dichiarare i parametri uno per uno.
    """
    modulo = await request.form()
    _check_csrf(user, str(modulo.get("csrf_token", "")))
    max_cifre = get_settings().ocr_max_digits
    pagina = str(modulo.get("pagina", "1"))

    with get_db() as conn:
        propri = {r["id"] for r in conn.execute(
            "SELECT id FROM media WHERE node_id=?", (node_id,)).fetchall()}
        for chiave, valore in modulo.items():
            if not chiave.startswith("numero_"):
                continue
            try:
                media_id = int(chiave[len("numero_"):])
            except ValueError:
                continue
            # si accettano solo foto che stanno davvero in questa cartella
            if media_id not in propri:
                continue
            numeri.imposta_manuali(conn, media_id,
                                   numeri.leggi_elenco(str(valore), max_cifre))

    log_event("INFO", "admin", f"Numeri corretti a mano nella cartella {node_id}")
    return RedirectResponse(url=f"/admin/numeri/{node_id}?pagina={pagina}",
                            status_code=status.HTTP_303_SEE_OTHER)


@router.post("/maintenance/scan")
def do_scan(request: Request, csrf_token: str = Form(...), full: str = Form("0"),
            user: dict = Depends(require_admin_api)):
    _check_csrf(user, csrf_token)
    result = scan(full=(full == "1"))
    log_event("INFO", "admin", f"Scan manuale: {result}")
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/maintenance/clear-cache")
def do_clear_cache(request: Request, csrf_token: str = Form(...),
                   user: dict = Depends(require_admin_api)):
    _check_csrf(user, csrf_token)
    n = clear_cache()
    log_event("INFO", "admin", f"Cache svuotata ({n})")
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)


# La pagina Impostazioni e' stata rimossa il 17/08/2026.
#
# Aveva dieci campi (titolo della home, testi di presentazione, descrizione
# per i motori di ricerca...) che venivano salvati nel database ma che
# nessuna pagina pubblica leggeva piu': da quando il sito e' in cinque
# lingue quei testi vivono in app/lingue.py. Erano comandi che non
# comandavano niente, e lasciarli faceva credere il contrario.
#
# get_setting e set_setting restano: le usano i raduni, per l'avviso e per
# la domanda di accesso.

# ---------------- Che cosa cerca la gente ----------------
# Senza moduli di contatto questa e' l'unica cosa che i visitatori riescono
# a dire: "ho cercato questo e non c'era". Le ricerche a vuoto indicano le
# gare che manca pubblicare e i numeri che la lettura automatica delle
# tabelle ha sbagliato.
@router.get("/ricerche", response_class=HTMLResponse)
def ricerche_page(request: Request, mostra: str = "vuote",
                  user: dict = Depends(require_admin_user)):
    if mostra not in ("vuote", "trovate", "tutte"):
        mostra = "vuote"
    filtro = {"vuote": " WHERE risultati = 0",
              "trovate": " WHERE risultati > 0",
              "tutte": ""}[mostra]
    with get_db() as conn:
        righe = conn.execute(
            "SELECT testo, numero, risultati, volte, primo_at, ultimo_at "
            "FROM ricerche" + filtro +
            " ORDER BY volte DESC, ultimo_at DESC LIMIT 300").fetchall()
        conteggi = conn.execute(
            "SELECT COUNT(*) tutte, "
            "       SUM(risultati = 0) vuote, "
            "       SUM(volte) totale "
            "FROM ricerche").fetchone()
    return templates.TemplateResponse(request, "admin/ricerche.html", {"user": user, "mostra": mostra,
        "righe": [dict(r) for r in righe],
        "conteggi": dict(conteggi)})


@router.post("/ricerche/dimentica")
def ricerche_dimentica(request: Request, testo: str = Form(...),
                       mostra: str = Form("vuote"),
                       csrf_token: str = Form(""),
                       user: dict = Depends(require_admin_user)):
    """Toglie una riga dal registro.

    Serve per le prove e per le ricerche senza senso: una volta pubblicata
    la gara che mancava, quella riga ha finito il suo compito.
    """
    _check_csrf(user, csrf_token)
    with get_db() as conn:
        conn.execute("DELETE FROM ricerche WHERE testo=?", (testo,))
    return RedirectResponse(url=f"/admin/ricerche?mostra={mostra}",
                            status_code=status.HTTP_303_SEE_OTHER)


@router.post("/ricerche/svuota")
def ricerche_svuota(request: Request, csrf_token: str = Form(""),
                    user: dict = Depends(require_admin_user)):
    _check_csrf(user, csrf_token)
    with get_db() as conn:
        conn.execute("DELETE FROM ricerche")
    log_event("INFO", "admin", "Registro delle ricerche svuotato")
    return RedirectResponse(url="/admin/ricerche",
                            status_code=status.HTTP_303_SEE_OTHER)


@router.get("/logs", response_class=HTMLResponse)
def logs_page(request: Request, user: dict = Depends(require_admin_user)):
    with get_db() as conn:
        rows = conn.execute("SELECT ts,level,category,message FROM logs ORDER BY id DESC LIMIT 200").fetchall()
    return templates.TemplateResponse(request, "admin/logs.html", {"user": user, "logs": [dict(r) for r in rows]})
