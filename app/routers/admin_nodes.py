"""Gestione amministrativa ad albero espandibile."""
import io
from datetime import datetime, timezone

import qrcode
from fastapi import APIRouter, BackgroundTasks, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response

from ..config import get_settings
from ..database import get_db, log_event, sottoalbero_like
from ..deps import require_admin_user, require_admin_api
from ..indexnow import notify_indexnow
from ..security import hash_password, verify_csrf, generate_access_token
from ..templating import templates
from .tree import _cerca_cartelle, _cover_molteplici

router = APIRouter(prefix="/admin/tree")


def _slug_sottoalbero(conn, rel_path: str) -> list:
    """Slug di un nodo e di tutto il suo sottoalbero — indipendentemente
    dal loro stato attuale di privacy/visibilita': la stessa pagina resta
    la stessa URL sia prima sia dopo un cambio di stato, cambia solo cosa
    risponde quella URL (contenuto o "non trovato")."""
    righe = conn.execute(
        "SELECT slug FROM nodes WHERE rel_path=? OR rel_path LIKE ? ESCAPE '\\'",
        (rel_path, sottoalbero_like(rel_path))).fetchall()
    return [r["slug"] for r in righe]


def _notifica_stato_cambiato(conn, background: BackgroundTasks, rel_path: str) -> None:
    """Manda a IndexNow, in un solo invio fuori dalla richiesta in corso,
    gli indirizzi di un nodo e del suo sottoalbero: vale sia per chi e'
    appena diventato pubblico (Bing deve scoprirlo) sia per chi e' appena
    diventato privato/nascosto (Bing deve accorgersi che quella pagina non
    c'e' piu')."""
    _notifica_piu_sottoalberi(conn, background, [rel_path])


def _notifica_piu_sottoalberi(conn, background: BackgroundTasks, rel_paths: list) -> None:
    """Come _notifica_stato_cambiato, ma per piu' nodi in un colpo solo (vedi
    bulk() qui sotto): un solo invio con tutti gli indirizzi insieme,
    invece di uno per nodo selezionato."""
    slugs = []
    for rel_path in rel_paths:
        slugs.extend(_slug_sottoalbero(conn, rel_path))
    if not slugs:
        return
    base = get_settings().site_url.rstrip("/")
    urls = [f"{base}/n/{s}" for s in dict.fromkeys(slugs)]
    background.add_task(notify_indexnow, urls)


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
        # Come nella parte pubblica: una copertina scelta a mano che punta a
        # una fotografia non piu' esistente ricade su quella automatica.
        if conn.execute("SELECT 1 FROM media WHERE id=?",
                        (r["cover_media_id"],)).fetchone():
            return r["cover_media_id"]
    row = conn.execute(
        "SELECT m.id FROM media m JOIN nodes n ON n.id=m.node_id "
        "WHERE (n.rel_path=? OR n.rel_path LIKE ? ESCAPE '\\') AND m.kind='image' "
        "ORDER BY m.filename LIMIT 1",
        (r["rel_path"], sottoalbero_like(r["rel_path"]))).fetchone()
    return row["id"] if row else None


def _serialize(conn, r, cover=None, has_children=None):
    """cover / has_children: se gia' calcolati in blocco per piu' righe
    (vedi api_children), si riusano cosi' come sono invece di rifare una
    query per singolo nodo."""
    return {
        "id": r["id"], "title": r["title"], "name": r["name"],
        "slug": r["slug"],
        "cover": cover if cover is not None else _cover_id(conn, r),
        "is_private": bool(r["is_private"]), "hidden": bool(r["hidden"]),
        "downloads_enabled": bool(r["downloads_enabled"]),
        "has_password": bool(r["password_hash"]),
        "access_token": r["access_token"], "total_media": r["total_media"],
        "direct_media": r["direct_media"], "depth": r["depth"],
        "has_children": (has_children if has_children is not None
                         else _has_children(conn, r["id"])),
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
        # Le copertine si calcolano tutte insieme (poche query, IN(...))
        # invece che una per riga: era l'N+1 principale di questo endpoint.
        copertine = _cover_molteplici(conn, rows)
        # Stesso trattamento per "ha figli?": una sola query con IN(...)
        # invece di una per nodo.
        ids = [r["id"] for r in rows]
        con_figli = set()
        if ids:
            segnaposto = ",".join("?" * len(ids))
            con_figli = {r["parent_id"] for r in conn.execute(
                f"SELECT DISTINCT parent_id FROM nodes WHERE parent_id IN ({segnaposto})", ids)}
        return JSONResponse([
            _serialize(conn, r, cover=copertine.get(r["id"]),
                      has_children=(r["id"] in con_figli))
            for r in rows
        ])


@router.get("/api/cerca")
def api_cerca(request: Request, q: str = "", user: dict = Depends(require_admin_user)):
    """Ricerca multi-parola per il pannello admin: riusa la stessa logica
    della ricerca pubblica (_cerca_cartelle in tree.py), ma con admin=True
    (include i privati) e includi_hidden=True (include anche i nascosti,
    che dal pannello devono restare raggiungibili anche se non compaiono
    mai nella navigazione pubblica)."""
    q = q.strip()
    if not q:
        return JSONResponse([])
    with get_db() as conn:
        trovati = _cerca_cartelle(conn, request, q, admin=True, includi_hidden=True)[:50]
        return JSONResponse([
            {
                "id": r["id"], "title": r["title"],
                "rel_path": r["rel_path"],
                "parent_path": r.get("parent_path"),
                "is_private": bool(r["is_private"]), "hidden": bool(r.get("hidden", 0)),
                "total_media": r["total_media"], "cover": r.get("cover"),
            }
            for r in trovati
        ])


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
        # Statistiche di apertura e download: per ogni album, pubblico o
        # privato. Non solo per i privati, per scelta esplicita.
        aperture = conn.execute(
            "SELECT COUNT(*) c, MIN(ts) prima, MAX(ts) ultima FROM node_stats "
            "WHERE node_id=? AND event='open'", (id,)).fetchone()
        download = conn.execute(
            "SELECT COUNT(*) c FROM node_stats WHERE node_id=? "
            "AND event IN ('download','zip')", (id,)).fetchone()
        d["stats"] = {
            "aperture": aperture["c"],
            "prima_apertura": aperture["prima"],
            "ultima_apertura": aperture["ultima"],
            "download": download["c"],
        }
        return JSONResponse(d)


@router.get("/{node_id}/qr")
def qr(request: Request, node_id: int, scarica: str = "",
       user: dict = Depends(require_admin_user)):
    """QR code dell'album, per stamparlo o passarlo al cliente al volo.

    Il contenuto del QR e' sempre e solo il link pubblico dell'album, lo
    stesso che il pannello mostra gia' in "Condivisione" per i privati o
    che compare come indirizzo /n/{slug} per quelli pubblici. Mai un dato
    interno (IP, percorso sul disco, token di sessione).

    Un album nascosto e basta (non privato) non ha nessun indirizzo che
    funzioni per chi non e' amministratore: /n/{slug} gli risponde 404.
    Generare comunque un QR sarebbe solo un codice che porta a una pagina
    inesistente, quindi qui si rifiuta con un messaggio chiaro invece di
    fingere che esista un link condivisibile."""
    with get_db() as conn:
        node = conn.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
    if not node:
        raise HTTPException(status_code=404, detail="Album non trovato")

    base = get_settings().site_url.rstrip("/")
    if node["is_private"]:
        if not node["access_token"]:
            raise HTTPException(status_code=409,
                detail="Questo album privato non ha ancora un link di condivisione: "
                       "generane uno dal pannello prima di creare il QR code")
        url = f"{base}/p/{node['access_token']}"
    elif node["hidden"]:
        raise HTTPException(status_code=409,
            detail="Questo album e' nascosto e non ha un indirizzo pubblico raggiungibile: "
                   "rendilo pubblico o privato con un link prima di creare il QR code")
    else:
        url = f"{base}/n/{node['slug']}"

    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    headers = {}
    if scarica == "1":
        headers["Content-Disposition"] = f'attachment; filename="qr-{node["slug"]}.png"'
    return Response(content=buf.getvalue(), media_type="image/png", headers=headers)


@router.get("/api/media")
def api_media(request: Request, node: int, user: dict = Depends(require_admin_user)):
    """Elenco delle sole fotografie dirette di un album, per scegliere la
    copertina dal pannello: niente sottocartelle, e' una scelta manuale
    fatta guardando cio' che sta davvero in quella cartella."""
    with get_db() as conn:
        n = conn.execute("SELECT id FROM nodes WHERE id=?", (node,)).fetchone()
        if not n:
            raise HTTPException(status_code=404, detail="Nodo non trovato")
        from .tree import _node_media
        media = _node_media(conn, node, offset=0, limit=1000)
        return JSONResponse([m for m in media if m["kind"] == "image"])


@router.post("/{node_id}/rename")
def rename(request: Request, node_id: int, csrf_token: str = Form(...),
           title: str = Form(...), user: dict = Depends(require_admin_api)):
    _check_csrf(user, csrf_token)
    t = title.strip() or "(senza titolo)"
    with get_db() as conn:
        conn.execute("UPDATE nodes SET title=?, updated_at=? WHERE id=?", (t, _now(), node_id))
    log_event("INFO", "admin", f"Rinominato nodo {node_id} -> '{t}'")
    return JSONResponse({"ok": True, "title": t})


def _set_hidden(conn, node_id, h):
    """Applica lo stato 'nascosto' a un nodo e a tutto il suo sottoalbero.
    Restituisce False se il nodo non esiste (nessuna eccezione: chi chiama
    in blocco su piu' nodi non deve fermarsi per un id inesistente)."""
    node = conn.execute("SELECT rel_path FROM nodes WHERE id=?", (node_id,)).fetchone()
    if not node:
        return False
    conn.execute("UPDATE nodes SET hidden=?, updated_at=? WHERE id=?", (h, _now(), node_id))
    conn.execute("UPDATE nodes SET hidden=? WHERE rel_path LIKE ? ESCAPE '\\'",
                 (h, sottoalbero_like(node["rel_path"])))
    return True


def _set_private(conn, node_id, private):
    """Applica lo stato 'privato' a un nodo e a tutto il suo sottoalbero,
    generando i link mancanti. Restituisce (ok, access_token)."""
    node = conn.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
    if not node:
        return False, None
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
    return True, (token if private else None)


@router.post("/{node_id}/hide")
def hide(request: Request, node_id: int, background: BackgroundTasks,
         csrf_token: str = Form(...), hidden: str = Form("0"),
         user: dict = Depends(require_admin_api)):
    _check_csrf(user, csrf_token)
    h = 1 if hidden == "1" else 0
    with get_db() as conn:
        node = conn.execute("SELECT rel_path FROM nodes WHERE id=?", (node_id,)).fetchone()
        if not node or not _set_hidden(conn, node_id, h):
            raise HTTPException(status_code=404, detail="Nodo non trovato")
        _notifica_stato_cambiato(conn, background, node["rel_path"])
    return JSONResponse({"ok": True, "hidden": bool(h)})


@router.post("/{node_id}/privacy")
def privacy(request: Request, node_id: int, background: BackgroundTasks,
            csrf_token: str = Form(...), is_private: str = Form("0"),
            user: dict = Depends(require_admin_api)):
    _check_csrf(user, csrf_token)
    private = 1 if is_private == "1" else 0
    with get_db() as conn:
        node = conn.execute("SELECT rel_path FROM nodes WHERE id=?", (node_id,)).fetchone()
        ok, token = _set_private(conn, node_id, private)
        if not ok:
            raise HTTPException(status_code=404, detail="Nodo non trovato")
        _notifica_stato_cambiato(conn, background, node["rel_path"])
    return JSONResponse({"ok": True, "is_private": bool(private), "access_token": token})


@router.post("/bulk")
def bulk(request: Request, background: BackgroundTasks, csrf_token: str = Form(...),
         node_ids: str = Form(...), azione: str = Form(...),
         user: dict = Depends(require_admin_api)):
    """Applica una delle quattro azioni di massa (pubblico/privato/nascondi/
    mostra) a un elenco di nodi, in una sola richiesta e una sola
    connessione. Gli id inesistenti nell'elenco vengono saltati senza far
    fallire gli altri: una singola voce sbagliata non deve bloccare il
    resto della selezione."""
    _check_csrf(user, csrf_token)
    if azione not in ("pubblico", "privato", "nascondi", "mostra"):
        raise HTTPException(status_code=400, detail="Azione non valida")
    ids = []
    for pezzo in node_ids.split(","):
        pezzo = pezzo.strip()
        if pezzo.isdigit():
            ids.append(int(pezzo))
    aggiornati = 0
    rel_paths = []
    with get_db() as conn:
        for nid in ids:
            node = conn.execute("SELECT rel_path FROM nodes WHERE id=?", (nid,)).fetchone()
            if azione == "pubblico":
                ok, _ = _set_private(conn, nid, 0)
            elif azione == "privato":
                ok, _ = _set_private(conn, nid, 1)
            elif azione == "nascondi":
                ok = _set_hidden(conn, nid, 1)
            else:  # mostra
                ok = _set_hidden(conn, nid, 0)
            if ok:
                aggiornati += 1
                rel_paths.append(node["rel_path"])
        # Una notifica per l'intera selezione, non una per album: chi
        # seleziona cinquanta cartelle e le rende pubbliche in blocco manda
        # una sola chiamata a IndexNow con tutti gli indirizzi, non cinquanta.
        _notifica_piu_sottoalberi(conn, background, rel_paths)
    return JSONResponse({"ok": True, "aggiornati": aggiornati, "richiesti": len(ids)})


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


@router.post("/{node_id}/copertina")
def copertina(request: Request, node_id: int, csrf_token: str = Form(...),
              media_id: str = Form(""), user: dict = Depends(require_admin_api)):
    """Sceglie a mano la fotografia di copertina di un album.

    Senza scelta la copertina resta quella automatica (la prima immagine
    per nome di file): mandare media_id vuoto rimette le cose com'erano,
    non lascia l'album senza copertina.

    La fotografia deve stare nell'album o in una sua sottocartella. Non
    basta che esista: una copertina presa da un altro album mostrerebbe
    in vetrina una foto che li' dentro non c'e', e in un album riservato
    farebbe uscire allo scoperto un'immagine di un album ancora chiuso.
    """
    _check_csrf(user, csrf_token)
    with get_db() as conn:
        nodo = conn.execute(
            "SELECT rel_path, is_private, hidden FROM nodes WHERE id=?",
            (node_id,)).fetchone()
        if not nodo:
            raise HTTPException(status_code=404, detail="Album non trovato")

        scelta = media_id.strip()
        if not scelta:
            conn.execute("UPDATE nodes SET cover_media_id=NULL, updated_at=? "
                         "WHERE id=?", (_now(), node_id))
            return JSONResponse({"ok": True, "cover_media_id": None,
                                 "automatica": True})

        if not scelta.isdigit():
            raise HTTPException(status_code=400, detail="Identificativo non valido")
        mid = int(scelta)

        # La foto deve appartenere all'album o a una sua sottocartella, e il
        # nodo che la contiene per davvero non puo' essere piu' riservato
        # dell'album di destinazione: un album pubblico non puo' pescare la
        # copertina da un sotto-album nascosto o privato annidato dentro,
        # altrimenti la vetrina pubblica mostrerebbe una fotografia che il
        # visitatore non ha diritto di vedere. Se l'album di destinazione e'
        # gia' privato o nascosto non c'e' fuga possibile: qualunque
        # sotto-album al suo interno e' comunque dietro la stessa porta.
        riga = conn.execute(
            "SELECT m.id FROM media m JOIN nodes n ON n.id=m.node_id "
            "WHERE m.id=? AND m.kind='image' "
            "AND (n.rel_path=? OR n.rel_path LIKE ? ESCAPE '\\')"
            "AND (? OR (COALESCE(n.is_private,0)=0 AND COALESCE(n.hidden,0)=0))",
            (mid, nodo["rel_path"], sottoalbero_like(nodo["rel_path"]),
             bool(nodo["is_private"]) or bool(nodo["hidden"]))).fetchone()
        if not riga:
            raise HTTPException(status_code=400,
                                detail="La fotografia non appartiene a questo album "
                                       "o non e' visibile nel suo contesto pubblico")

        conn.execute("UPDATE nodes SET cover_media_id=?, updated_at=? WHERE id=?",
                     (mid, _now(), node_id))
    return JSONResponse({"ok": True, "cover_media_id": mid, "automatica": False})


@router.post("/media/{media_id}/share")
def media_share(request: Request, media_id: int, csrf_token: str = Form(...),
                user: dict = Depends(require_admin_api)):
    """Condivisione della singola fotografia: get-or-create dello share_token,
    stesso schema del token dei link privati (secrets.token_urlsafe(16))."""
    _check_csrf(user, csrf_token)
    with get_db() as conn:
        m = conn.execute("SELECT id, share_token FROM media WHERE id=?", (media_id,)).fetchone()
        if not m:
            raise HTTPException(status_code=404, detail="Fotografia non trovata")
        token = m["share_token"]
        if not token:
            token = generate_access_token()
            conn.execute(
                "UPDATE media SET share_token=?, share_created_at=? WHERE id=?",
                (token, _now(), media_id))
        from ..config import get_settings
        base = get_settings().site_url.rstrip("/")
        return JSONResponse({"ok": True, "share_token": token, "url": f"{base}/f/{token}"})


@router.post("/media/{media_id}/share/revoke")
def media_share_revoke(request: Request, media_id: int, csrf_token: str = Form(...),
                       user: dict = Depends(require_admin_api)):
    _check_csrf(user, csrf_token)
    with get_db() as conn:
        m = conn.execute("SELECT id FROM media WHERE id=?", (media_id,)).fetchone()
        if not m:
            raise HTTPException(status_code=404, detail="Fotografia non trovata")
        conn.execute(
            "UPDATE media SET share_token=NULL, share_created_at=NULL WHERE id=?",
            (media_id,))
    return JSONResponse({"ok": True})


@router.post("/condivisioni/{condivisione_id}/revoca")
def condivisione_revoca(request: Request, condivisione_id: int, csrf_token: str = Form(...),
                        user: dict = Depends(require_admin_api)):
    """Revoca un link di condivisione per selezione multipla (/fs/{token}).

    Cancella la riga in condivisioni: nessuna tabella ha una foreign key su
    condivisioni.id, quindi non c'e' nulla da lasciare orfano. Il token
    smette immediatamente di funzionare su tutte le rotte /fs/{token}/...,
    che fanno tutte SELECT ... FROM condivisioni WHERE token=? e rispondono
    404 se la riga non c'e' piu' (stesso comportamento di un token mai
    esistito, non serve un campo di stato separato)."""
    _check_csrf(user, csrf_token)
    with get_db() as conn:
        row = conn.execute("SELECT id FROM condivisioni WHERE id=?",
                           (condivisione_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Condivisione non trovata")
        conn.execute("DELETE FROM condivisioni WHERE id=?", (condivisione_id,))
    return JSONResponse({"ok": True})


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


@router.post("/media/{media_id}/share/scadenza")
def imposta_scadenza_foto(media_id: int, csrf_token: str = Form(...),
                          giorni: str = Form("0"),
                          user: dict = Depends(require_admin_api)):
    """Imposta o toglie la scadenza del link di condivisione di una
    fotografia singola. Stesso pattern di imposta_scadenza per gli album:
    NULL/stringa vuota = nessuna scadenza, comportamento di sempre."""
    _check_csrf(user, csrf_token)
    from .tree import calcola_scadenza
    valore = calcola_scadenza(giorni)
    with get_db() as conn:
        conn.execute("UPDATE media SET share_expires_at=? WHERE id=?", (valore, media_id))
    log_event("INFO", "share",
              f"Scadenza link foto {media_id}: " + (valore[:10] if valore else "illimitata"))
    return JSONResponse({"ok": True, "expires_at": valore})


@router.post("/condivisioni/{condivisione_id}/scadenza")
def imposta_scadenza_selezione(condivisione_id: int, csrf_token: str = Form(...),
                               giorni: str = Form("0"),
                               user: dict = Depends(require_admin_api)):
    """Come sopra, per il link di una selezione multipla."""
    _check_csrf(user, csrf_token)
    from .tree import calcola_scadenza
    valore = calcola_scadenza(giorni)
    with get_db() as conn:
        conn.execute("UPDATE condivisioni SET expires_at=? WHERE id=?", (valore, condivisione_id))
    log_event("INFO", "share",
              f"Scadenza link selezione {condivisione_id}: " + (valore[:10] if valore else "illimitata"))
    return JSONResponse({"ok": True, "expires_at": valore})
