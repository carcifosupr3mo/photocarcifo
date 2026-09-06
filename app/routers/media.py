"""Router media: miniature, anteprime, download singolo, video, ZIP.

Controllo accessi: i file di cartelle private o nascoste sono scaricabili
solo da un amministratore o da chi ha sbloccato quella cartella con la
password. Impedisce di raggiungere le foto di uno shooting privato
indovinando gli identificativi.
"""
import secrets
from datetime import datetime, timezone
from urllib.parse import quote

import zipstream
from fastapi import APIRouter, Form, HTTPException, Request, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse

from ..config import get_settings
from ..database import get_db, record_node_stat, record_stat
from ..deps import get_current_user
from ..security import generate_access_token
from ..templating import templates
from ..thumbnails import (get_or_create_thumbnail, SIZE_SMALL,
                          SIZE_CARD, SIZE_MEDIUM, SIZE_COVER, SIZE_SOCIAL,
                          FORMATO_JPEG, FORMATO_WEBP, FORMATO_AVIF, TIPO_MIME)
from ..zip_lock import (ArchivioGiaInPreparazione, chiave_album,
                        chiave_selezione, lucchetto_zip)
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
                expires_at=None, via_share: bool = False) -> bool:
    """Admin sempre; gli altri solo da cartelle pubbliche o gia' sbloccate,
    e mai da un link di condivisione scaduto.

    via_share: vero solo quando si arriva dal link di condivisione di una
    singola fotografia (/f/{token}). In quel caso, per un album privato,
    il link della foto vale come lasciapassare per quella foto soltanto —
    ma solo se l'album non e' nascosto o scaduto: quei due controlli
    restano PRIMA di questo apposta, cosi' nascondere un album blocca
    anche i link diretti alle sue foto. Nessuna delle rotte generiche
    (/thumb, /preview, /video, /zip/*, /download/{id}, identificate da
    media_id) passa via_share=True: lo fa solo la famiglia di rotte
    /f/{token}/... della condivisione singola, identificate dal token."""
    if _is_admin(request):
        return True
    if hidden:
        return False
    if scaduto(expires_at):
        return False
    if is_private:
        return via_share or _is_unlocked(request, node_id)
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


# Il numero piu' grande che SQLite sa tenere in un intero. Oltre questo
# Python regge (i suoi interi non hanno tetto) ma il database no, e la
# query si spezzava con un errore di servizio invece di una risposta
# ordinata: chi manda un identificativo assurdo ha sbagliato richiesta,
# non ha rotto il sito.
_MAX_SQLITE_INT = 2 ** 63 - 1


def _ids_da_elenco(ids: str, tetto: int = 2000) -> list:
    """Trasforma un elenco "1,2,3" nell'elenco di numeri buoni per il
    database: scarta cio' che non e' cifra e cio' che il database non sa
    contenere, e si ferma al tetto."""
    fuori = []
    for x in ids.split(","):
        x = x.strip()
        if not x.isdigit():
            continue
        n = int(x)
        if 0 < n <= _MAX_SQLITE_INT:
            fuori.append(n)
        if len(fuori) >= tetto:
            break
    return fuori


def _thumb_response(request: Request, m, size: str):
    """Genera/streamma la miniatura per una riga media gia' autorizzata.

    Fattorizzato fuori da _serve_thumb(): serve anche alla condivisione
    della singola fotografia (/f/{token}/anteprima e /f/{token}/miniatura),
    che deve fare esattamente la stessa cosa dopo aver verificato l'accesso
    con via_share=True invece che con il cookie di sblocco album."""
    # L'anteprima social va sempre in JPEG: i programmi che leggono i
    # collegamenti nelle chat non dichiarano di sapere leggere il WebP e
    # alcuni non lo aprono affatto.
    formato = FORMATO_JPEG if size == SIZE_SOCIAL else _formato_per(request)
    thumb = get_or_create_thumbnail(m["rel_path"], m["mtime"], m["kind"],
                                    size, formato)
    # Se per qualche motivo il formato scelto non si e' potuto creare, si
    # ripiega sul JPEG invece di lasciare un riquadro vuoto. Il ripiego va
    # tentato solo se non si era gia' chiesto JPEG: chiamare di nuovo la
    # stessa generazione con lo stesso formato rifarebbe lo stesso lavoro
    # (e lo stesso fallimento) una seconda volta inutilmente.
    if (not thumb or not thumb.exists()) and formato != FORMATO_JPEG:
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


def _serve_thumb(request: Request, media_id: int, size: str):
    """Le anteprime di cartelle private o nascoste sono servite solo a chi
    ha diritto di vederle: senza questo controllo basterebbe indovinare un
    identificativo per sfogliare uno shooting riservato."""
    m = _get_media(media_id)
    if not _can_access(request, m["nid"], m["is_private"], m["hidden"], m["expires_at"]):
        raise HTTPException(status_code=404, detail="Non disponibile")
    return _thumb_response(request, m, size)


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


@router.post("/condividi/selezione")
def condividi_selezione(request: Request, ids: str = Form(...)):
    """Get-or-create del link di condivisione per una selezione di piu'
    fotografie insieme (galleria + ZIP), stessa logica pubblica/idempotente
    di condividi() ma su un elenco di ID invece che su uno solo.

    ids arriva nel corpo del POST e non nella query string: con selezioni
    fino a 2000 foto l'elenco supererebbe la lunghezza ragionevole di un URL.

    Gli ID vengono filtrati con _can_access riga per riga, esattamente come
    zip_select: chi non ha diritto di vedere una foto non la fa comparire
    nel link generato, in silenzio, senza errore ne' elenco di quali sono
    state scartate (altrimenti si potrebbe usare la selezione per scoprire
    quali ID esistono in un album privato). Se dopo il filtro non resta
    nulla, 400 come zip_select quando la selezione e' vuota.

    Idempotenza: il token si genera su una rappresentazione ordinata e
    deduplicata degli ID accessibili, cosi' ricondividere la stessa
    selezione (anche in ordine diverso) riusa lo stesso link invece di
    crearne uno nuovo a ogni click."""
    id_list = _ids_da_elenco(ids)
    if not id_list:
        raise HTTPException(status_code=400, detail="Selezione vuota")
    placeholders = ",".join("?" * len(id_list))
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT m.id, n.id AS nid, n.is_private, n.hidden, n.expires_at "
            f"FROM media m JOIN nodes n ON n.id=m.node_id "
            f"WHERE m.id IN ({placeholders})", id_list).fetchall()
    accessibili = sorted({
        r["id"] for r in rows
        if _can_access(request, r["nid"], r["is_private"], r["hidden"], r["expires_at"])
    })
    if not accessibili:
        raise HTTPException(status_code=400, detail="Selezione vuota")
    chiave = ",".join(str(i) for i in accessibili)
    with get_db() as conn:
        row = conn.execute(
            "SELECT token FROM condivisioni WHERE media_ids=?", (chiave,)).fetchone()
        token = row["token"] if row else None
        if not token:
            token = generate_access_token()
            conn.execute(
                "INSERT INTO condivisioni(token, media_ids, created_at) VALUES(?,?,?)",
                (token, chiave, datetime.now(timezone.utc).isoformat()))
    base = get_settings().site_url.rstrip("/")
    # Anteprima del pannello di condivisione: la selezione non ha un'unica
    # foto da mostrare, quindi se ne sceglie una a caso fra quelle
    # accessibili. La scelta la fa il server perche' solo qui si sa quali
    # ID sono sopravvissuti al filtro _can_access: il browser conosce gli
    # ID che ha mandato, non quelli effettivamente condivisi, e mostrarne
    # uno scartato darebbe un'anteprima vuota (o rivelerebbe che esiste).
    # L'indirizzo e' quello della miniatura gia' vincolata al token.
    scelta = secrets.choice(accessibili)
    return JSONResponse({
        "ok": True,
        "share_token": token,
        "url": f"{base}/fs/{token}",
        "anteprima": f"{base}/fs/{token}/miniatura/{scelta}",
        "conta": len(accessibili),
    })


@router.post("/condividi/{media_id}")
def condividi(request: Request, media_id: int):
    """Get-or-create del link di condivisione di una singola fotografia,
    ma accessibile a QUALSIASI visitatore dalla griglia dell'album, non
    solo all'amministratore (a differenza di /admin/tree/media/{id}/share).

    Nessun require_admin_api e nessun CSRF: l'azione non e' distruttiva, e'
    idempotente (get-or-create) e non richiede stato autenticato, come le
    altre rotte pubbliche del progetto.

    L'assenza di CSRF e' sicura finche' il cookie di sblocco album resta
    SameSite=Lax (vedi tree.py, _UNLOCK_COOKIE): un POST cross-site non
    porta con se' quel cookie, quindi _can_access nega comunque l'accesso
    a foto private. Se in futuro quel SameSite cambiasse, va rivalutato.

    Il controllo di accesso e' lo stesso di /preview/{media_id}: via_share
    resta a False (default) perche' qui si sta GENERANDO l'accesso al
    token, non consumandolo da un link gia' esistente. Passare True
    permetterebbe a chiunque di generare un link di condivisione per foto
    di album privati a cui non ha accesso.

    Nota: dichiarata DOPO /condividi/selezione apposta, altrimenti FastAPI
    proverebbe a interpretare "selezione" come questo {media_id}: int e
    fallirebbe con 422 invece di instradare alla rotta giusta."""
    m = _get_media(media_id)
    if not _can_access(request, m["nid"], m["is_private"], m["hidden"], m["expires_at"]):
        raise HTTPException(status_code=404, detail="Non disponibile")
    with get_db() as conn:
        row = conn.execute("SELECT share_token FROM media WHERE id=?", (media_id,)).fetchone()
        token = row["share_token"] if row else None
        if not token:
            token = generate_access_token()
            conn.execute(
                "UPDATE media SET share_token=?, share_created_at=? WHERE id=?",
                (token, datetime.now(timezone.utc).isoformat(), media_id))
    base = get_settings().site_url.rstrip("/")
    return JSONResponse({"ok": True, "share_token": token, "url": f"{base}/f/{token}"})


def _video_response(settings, m):
    """Consegna il file video al browser per una riga media gia' autorizzata.

    Fattorizzato fuori da video(): serve anche a /f/{token}/video, che deve
    fare esattamente la stessa cosa senza duplicare la logica di
    X-Accel-Redirect / FileResponse."""
    if settings.use_xaccel:
        return Response(status_code=200, headers={
            "X-Accel-Redirect": f"/_originals/{quote(m['rel_path'])}",
            "Content-Type": "video/mp4", "Accept-Ranges": "bytes"})
    source = settings.photo_root_path / m["rel_path"]
    if not source.exists():
        raise HTTPException(status_code=404, detail="Video non trovato")
    return FileResponse(str(source), media_type="video/mp4")


@router.get("/video/{media_id}")
def video(media_id: int, request: Request):
    settings = get_settings()
    m = _get_media(media_id)
    if m["kind"] != "video":
        raise HTTPException(status_code=404, detail="Non e un video")
    if not _can_access(request, m["nid"], m["is_private"], m["hidden"], m["expires_at"]):
        raise HTTPException(status_code=403, detail="Accesso non consentito")
    return _video_response(settings, m)


def _stream_original(settings, m):
    """Consegna il file originale al browser.

    Fattorizzato fuori da download(): serve anche alla condivisione della
    singola fotografia (/f/{token}/download), che deve fare esattamente la
    stessa cosa senza duplicare la logica di X-Accel-Redirect / FileResponse.
    """
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
    record_node_stat(m["node_id"], "download")
    return _stream_original(settings, m)


def _zip_stream(files):
    z = zipstream.ZipFile(mode="w", compression=zipstream.ZIP_STORED)
    for abs_path, arcname in files:
        z.write(str(abs_path), arcname=arcname)
    for chunk in z:
        yield chunk


class _RispostaZipConLucchetto(StreamingResponse):
    """Una StreamingResponse che libera il lucchetto qualunque sia la
    sorte dell'invio.

    Non basta un finally dentro _zip_stream: provato con un generatore
    lento e una disconnessione a meta' strada, Starlette non lo richiude
    mai, resta sospeso per sempre e il suo finally non scatta. Non basta
    nemmeno il parametro background di StreamingResponse: provato con un
    generatore che solleva un'eccezione a meta' streaming, il background
    non viene eseguito, l'eccezione lo scavalca. L'unico punto verificato
    che scatta sempre nei tre casi (successo, eccezione, disconnessione)
    e' un try/finally intorno all'invio vero e proprio — qui sotto."""

    def __init__(self, *args, chiudi_lucchetto, **kwargs):
        super().__init__(*args, **kwargs)
        self._chiudi_lucchetto = chiudi_lucchetto

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._chiudi_lucchetto()


def _risposta_zip_occupato(messaggio: str, segnale: str) -> JSONResponse:
    """La risposta quando un altro processo tiene gia' il lucchetto dello
    stesso archivio.

    Lo status resta 409 per davvero (una richiesta diretta all'endpoint,
    fuori dal sito, lo vede correttamente): ma il download parte dal click
    su un collegamento, non da una fetch, e una navigazione non lascia al
    JavaScript il modo di leggere il codice di stato. La pagina che ha
    chiesto lo ZIP se ne accorge percio' con lo stesso meccanismo che gia'
    usa per sapere quando l'archivio e' pronto: un biscottino, con un
    valore diverso da quello del successo, che la spia gia' in ascolto
    riconosce subito senza bisogno di un secondo meccanismo.

    Il nome del file serve a chi scarica, non al programma: il collegamento
    ha l'attributo download, quindi il browser salva qualunque cosa arrivi,
    anche questa risposta. Senza un nome dichiarato finirebbe fra le
    fotografie un "select.json" che non spiega niente; cosi' almeno il nome
    dice cos'e'."""
    risposta = JSONResponse({"ok": False, "detail": messaggio},
                            status_code=409)
    risposta.headers["Content-Disposition"] = (
        "attachment; filename=\"archivio-gia-in-preparazione.json\"")
    if segnale:
        risposta.set_cookie("pc_zip", "occupato:" + segnale, max_age=60,
                            path="/", samesite="lax", secure=True)
    return risposta


def _risposta_zip(files, nome_file: str, segnale: str = "",
                  chiave_lock: str = "") -> StreamingResponse:
    """La risposta con l'archivio, piu' il segnale che il lavoro e' partito.

    L'archivio si costruisce mentre viene mandato, quindi la sua lunghezza
    non si sa in anticipo (Transfer-Encoding: chunked) e una percentuale
    sarebbe inventata. Quello che si puo' dire e' che il server ha preso
    in carico la richiesta: lo si scrive in un biscottino non appena
    partono gli header della risposta (non quando il primo file
    dell'archivio e' davvero pronto), e la pagina lo controlla per
    togliere l'avviso di attesa. Senza, chi ha chiesto trecento
    fotografie resta davanti a uno schermo fermo e preme di nuovo.

    Il biscottino non identifica nessuno: contiene solo il numero che la
    pagina ha appena mandato, dura un minuto (il tempo che la pagina si da'
    per aspettare prima di rassegnarsi) e viaggia solo su HTTPS, come tutto
    il resto del sito.

    chiave_lock, se data, prende il lucchetto su tutta la macchina prima
    di aprire un solo file: due richieste per lo stesso identico archivio
    (stesso album, o stessa selezione anche in ordine diverso) non
    comprimono mai gli stessi file due volte in parallelo. Solleva
    ArchivioGiaInPreparazione se un altro processo lo tiene gia' — il
    chiamante la trasforma in 409, prima ancora di aprire il primo file.
    """
    intestazioni = {"Content-Disposition":
                    "attachment; filename*=UTF-8''" + nome_file}
    if chiave_lock:
        lucchetto = lucchetto_zip(chiave_lock)
        lucchetto.__enter__()  # solleva ArchivioGiaInPreparazione se occupato
        chiudi = lambda: lucchetto.__exit__(None, None, None)
    else:
        chiudi = lambda: None
    try:
        risposta = _RispostaZipConLucchetto(
            _zip_stream(files), media_type="application/zip",
            headers=intestazioni, chiudi_lucchetto=chiudi)
    except BaseException:
        chiudi()
        raise
    if segnale:
        risposta.set_cookie("pc_zip", segnale, max_age=60, path="/",
                            samesite="lax", secure=True)
    return risposta


@router.get("/zip/node/{node_id}")
def zip_node(node_id: int, request: Request, segnale: str = Query("")):
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
    record_node_stat(node_id, "zip")
    zipname = quote(f"{node['title']}.zip")
    try:
        return _risposta_zip(files, zipname, segnale=segnale,
                             chiave_lock=chiave_album(node_id))
    except ArchivioGiaInPreparazione as e:
        return _risposta_zip_occupato(str(e), segnale)


@router.get("/zip/select")
def zip_select(request: Request, ids: str = Query(...), segnale: str = Query("")):
    settings = get_settings()
    id_list = _ids_da_elenco(ids)
    if not id_list:
        raise HTTPException(status_code=400, detail="Selezione vuota")
    placeholders = ",".join("?" * len(id_list))
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT m.id AS mid, m.rel_path, m.filename, n.id AS nid, "
            f"n.is_private, n.hidden, n.expires_at "
            f"FROM media m JOIN nodes n ON n.id=m.node_id "
            f"WHERE m.id IN ({placeholders}) AND n.downloads_enabled=1", id_list).fetchall()
    files = []
    nodi_coinvolti = set()
    id_accettati = []
    for r in rows:
        if not _can_access(request, r["nid"], r["is_private"], r["hidden"], r["expires_at"]):
            continue
        p = settings.photo_root_path / r["rel_path"]
        if p.exists():
            files.append((p, r["filename"]))
            nodi_coinvolti.add(r["nid"])
            id_accettati.append(r["mid"])
    if not files:
        raise HTTPException(status_code=403, detail="Nessun file scaricabile")
    record_stat("zip_select", str(len(files)))
    # I file possono appartenere a nodi diversi: una sola chiamata per
    # ogni nodo distinto della selezione accettata, non una per file.
    for nid in nodi_coinvolti:
        record_node_stat(nid, "zip")
    # La chiave nasce dagli id davvero accettati dopo _can_access, non da
    # quelli grezzi della richiesta: due persone con permessi diversi che
    # chiedono nominalmente la stessa selezione possono ottenere file
    # diversi, e non sono lo stesso archivio da deduplicare.
    try:
        return _risposta_zip(files, "selezione.zip", segnale=segnale,
                             chiave_lock=chiave_selezione(id_accettati))
    except ArchivioGiaInPreparazione as e:
        return _risposta_zip_occupato(str(e), segnale)


# --- Condivisione della singola fotografia -------------------------------
# Oggi si condivide solo l'album intero: qui si manda a chi la interessa
# una sola fotografia, con un token indipendente dall'album (media.share_token).
# La sicurezza resta interamente in _can_access(): questa rotta le passa
# via_share=True, che vale solo qui e apre l'album SOLO per quella foto.


def _get_media_by_share(token: str):
    """La fotografia (e il suo nodo) identificata da un token di
    condivisione. Query pensata per restituire al massimo UNA riga: il
    token e' UNIQUE (idx_media_share), quindi non puo' mai esporre altri
    file dello stesso album."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT m.id, m.rel_path, m.filename, m.mtime, m.kind, m.node_id, "
            "n.downloads_enabled, n.is_private, n.hidden, n.expires_at, n.id AS nid, "
            "m.share_expires_at "
            "FROM media m JOIN nodes n ON n.id=m.node_id "
            "WHERE m.share_token=? LIMIT 1",
            (token,)).fetchone()
    if row and scaduto(row["share_expires_at"]):
        return None
    return row


@router.get("/f/{token}", response_class=HTMLResponse)
def foto_condivisa(request: Request, token: str):
    m = _get_media_by_share(token)
    if not m:
        return templates.TemplateResponse(request, "public/media_share.html",
            {"trovata": False, "media": None}, status_code=404)
    if not _can_access(request, m["nid"], m["is_private"], m["hidden"], m["expires_at"], via_share=True):
        return templates.TemplateResponse(request, "public/media_share.html",
            {"trovata": False, "media": None}, status_code=404)
    record_node_stat(m["node_id"], "open")
    return templates.TemplateResponse(request, "public/media_share.html", {
        "trovata": True, "media": dict(m), "token": token,
        "downloads_enabled": bool(m["downloads_enabled"])})


@router.get("/f/{token}/download")
def foto_condivisa_download(request: Request, token: str):
    settings = get_settings()
    m = _get_media_by_share(token)
    if not m:
        raise HTTPException(status_code=404, detail="Non disponibile")
    if not m["downloads_enabled"]:
        raise HTTPException(status_code=403, detail="Download disabilitato")
    if not _can_access(request, m["nid"], m["is_private"], m["hidden"], m["expires_at"], via_share=True):
        raise HTTPException(status_code=404, detail="Non disponibile")
    record_stat("download", m["rel_path"])
    record_node_stat(m["node_id"], "download")
    return _stream_original(settings, m)


@router.get("/f/{token}/anteprima")
def foto_condivisa_anteprima(request: Request, token: str):
    """Immagine principale della pagina di condivisione singola.

    La pagina /f/{token} concede l'accesso alla pagina HTML con
    via_share=True, ma <img src="..."> e' una richiesta a parte: se puntasse
    a /preview/{id}, quella rotta verificherebbe via cookie di sblocco
    album, che chi arriva dal link della singola foto non ha mai. Questa
    rotta rifa' lo stesso controllo via_share=True, cosi' l'immagine si
    carica davvero."""
    m = _get_media_by_share(token)
    if not m:
        raise HTTPException(status_code=404, detail="Non disponibile")
    if not _can_access(request, m["nid"], m["is_private"], m["hidden"], m["expires_at"], via_share=True):
        raise HTTPException(status_code=404, detail="Non disponibile")
    return _thumb_response(request, m, SIZE_MEDIUM)


@router.get("/f/{token}/miniatura")
def foto_condivisa_miniatura(request: Request, token: str):
    """Versione doppia della miniatura per la pagina di condivisione
    (srcset ad alta densita'), stesso motivo di foto_condivisa_anteprima."""
    m = _get_media_by_share(token)
    if not m:
        raise HTTPException(status_code=404, detail="Non disponibile")
    if not _can_access(request, m["nid"], m["is_private"], m["hidden"], m["expires_at"], via_share=True):
        raise HTTPException(status_code=404, detail="Non disponibile")
    return _thumb_response(request, m, SIZE_CARD)


@router.get("/f/{token}/social")
def foto_condivisa_social(request: Request, token: str):
    """Immagine per il tag og:image della pagina di condivisione: chi la
    richiede e' il bot della chat/social, mai il browser con il cookie di
    sblocco album, quindi deve passare anche lei da via_share=True."""
    m = _get_media_by_share(token)
    if not m:
        raise HTTPException(status_code=404, detail="Non disponibile")
    if not _can_access(request, m["nid"], m["is_private"], m["hidden"], m["expires_at"], via_share=True):
        raise HTTPException(status_code=404, detail="Non disponibile")
    return _thumb_response(request, m, SIZE_SOCIAL)


@router.get("/f/{token}/video")
def foto_condivisa_video(request: Request, token: str):
    """Streaming del video per la pagina di condivisione, stesso motivo di
    foto_condivisa_anteprima ma per i video."""
    settings = get_settings()
    m = _get_media_by_share(token)
    if not m:
        raise HTTPException(status_code=404, detail="Non disponibile")
    if m["kind"] != "video":
        raise HTTPException(status_code=404, detail="Non e un video")
    if not _can_access(request, m["nid"], m["is_private"], m["hidden"], m["expires_at"], via_share=True):
        raise HTTPException(status_code=404, detail="Non disponibile")
    return _video_response(settings, m)


# --- Condivisione di una selezione di piu' fotografie ---------------------
# Stesso principio della condivisione singola (token indipendente,
# via_share=True), ma il token vive nella tabella condivisioni e punta a un
# elenco di media_id invece che a una sola riga. Le foto possono appartenere
# ad album diversi: si mostrano tutte insieme in un'unica galleria.


def _get_selezione_by_share(token: str):
    """Le righe media (con il loro nodo) della collezione identificata dal
    token, nello stesso ordine salvato alla creazione del link. Ogni riga
    porta gia' is_private/hidden/expires_at del proprio nodo: _can_access va
    comunque riverificato qui (non solo alla creazione del link) perche' un
    album puo' diventare privato o nascosto DOPO che il link e' stato
    generato, e in quel caso il link deve smettere di funzionare."""
    with get_db() as conn:
        riga = conn.execute(
            "SELECT media_ids, expires_at FROM condivisioni WHERE token=?", (token,)).fetchone()
        if not riga:
            return None
        if scaduto(riga["expires_at"]):
            return None
        id_list = _ids_da_elenco(riga["media_ids"], tetto=2000)
        if not id_list:
            return []
        placeholders = ",".join("?" * len(id_list))
        rows = conn.execute(
            f"SELECT m.id, m.rel_path, m.filename, m.mtime, m.kind, m.node_id, "
            f"n.downloads_enabled, n.is_private, n.hidden, n.expires_at, n.id AS nid "
            f"FROM media m JOIN nodes n ON n.id=m.node_id "
            f"WHERE m.id IN ({placeholders})", id_list).fetchall()
    per_id = {r["id"]: r for r in rows}
    # Riordina secondo l'elenco salvato: la query IN non garantisce l'ordine,
    # e senza questo passaggio la galleria mescolerebbe l'ordine a ogni
    # visita.
    return [per_id[i] for i in id_list if i in per_id]


@router.get("/fs/{token}", response_class=HTMLResponse)
def selezione_condivisa(request: Request, token: str):
    righe = _get_selezione_by_share(token)
    if righe is None:
        return templates.TemplateResponse(request, "public/media_share_multi.html",
            {"trovata": False, "media_list": []}, status_code=404)
    accessibili = [r for r in righe if _can_access(
        request, r["nid"], r["is_private"], r["hidden"], r["expires_at"], via_share=True)]
    if not accessibili:
        return templates.TemplateResponse(request, "public/media_share_multi.html",
            {"trovata": False, "media_list": []}, status_code=404)
    for nid in {r["nid"] for r in accessibili}:
        record_node_stat(nid, "open")
    # Il pulsante "scarica tutte" appare solo se OGNI foto della collezione
    # ha i download abilitati: mostrarlo quando anche una sola foto viene
    # da un album con downloads_enabled=0 servirebbe quella foto comunque,
    # dentro lo ZIP, aggirando il divieto messo sul suo album.
    downloads_enabled = all(bool(r["downloads_enabled"]) for r in accessibili)
    return templates.TemplateResponse(request, "public/media_share_multi.html", {
        "trovata": True, "media_list": [dict(r) for r in accessibili], "token": token,
        "downloads_enabled": downloads_enabled})


@router.get("/fs/{token}/miniatura/{media_id}")
def selezione_condivisa_miniatura(request: Request, token: str, media_id: int):
    """Miniatura di una foto della collezione. media_id deve far parte
    della collezione indicata dal token, altrimenti non e' un lasciapassare
    valido per quella foto (stesso motivo delle rotte /f/{token}/... della
    condivisione singola: /thumb/{id} controllerebbe con il cookie di
    sblocco album, che qui non c'e' mai)."""
    righe = _get_selezione_by_share(token)
    if not righe:
        raise HTTPException(status_code=404, detail="Non disponibile")
    m = next((r for r in righe if r["id"] == media_id), None)
    if not m or not _can_access(request, m["nid"], m["is_private"], m["hidden"],
                                m["expires_at"], via_share=True):
        raise HTTPException(status_code=404, detail="Non disponibile")
    return _thumb_response(request, m, SIZE_CARD)


@router.get("/fs/{token}/anteprima/{media_id}")
def selezione_condivisa_anteprima(request: Request, token: str, media_id: int):
    righe = _get_selezione_by_share(token)
    if not righe:
        raise HTTPException(status_code=404, detail="Non disponibile")
    m = next((r for r in righe if r["id"] == media_id), None)
    if not m or not _can_access(request, m["nid"], m["is_private"], m["hidden"],
                                m["expires_at"], via_share=True):
        raise HTTPException(status_code=404, detail="Non disponibile")
    return _thumb_response(request, m, SIZE_MEDIUM)


@router.get("/fs/{token}/download/{media_id}")
def selezione_condivisa_download(request: Request, token: str, media_id: int):
    """Download della singola fotografia dalla galleria della collezione,
    stesso motivo di selezione_condivisa_miniatura: media_id deve far parte
    della collezione indicata dal token."""
    settings = get_settings()
    righe = _get_selezione_by_share(token)
    if not righe:
        raise HTTPException(status_code=404, detail="Non disponibile")
    m = next((r for r in righe if r["id"] == media_id), None)
    if not m:
        raise HTTPException(status_code=404, detail="Non disponibile")
    if not m["downloads_enabled"]:
        raise HTTPException(status_code=403, detail="Download disabilitato")
    if not _can_access(request, m["nid"], m["is_private"], m["hidden"],
                       m["expires_at"], via_share=True):
        raise HTTPException(status_code=404, detail="Non disponibile")
    record_stat("download", m["rel_path"])
    record_node_stat(m["node_id"], "download")
    return _stream_original(settings, m)


@router.get("/fs/{token}/zip")
def selezione_condivisa_zip(request: Request, token: str, segnale: str = Query("")):
    settings = get_settings()
    righe = _get_selezione_by_share(token)
    if not righe:
        raise HTTPException(status_code=404, detail="Non disponibile")
    accessibili = [r for r in righe if _can_access(
        request, r["nid"], r["is_private"], r["hidden"], r["expires_at"], via_share=True)]
    if not accessibili:
        raise HTTPException(status_code=404, detail="Non disponibile")
    # Stesso motivo dello stesso controllo in selezione_condivisa(): se una
    # sola foto della collezione viene da un album con i download disattivati,
    # tutto lo ZIP resta bloccato invece di lasciarla scaricare di nascosto
    # dentro l'archivio.
    if not all(bool(r["downloads_enabled"]) for r in accessibili):
        raise HTTPException(status_code=403, detail="Download disabilitato")
    files = []
    nodi_coinvolti = set()
    id_accettati = []
    for r in accessibili:
        p = settings.photo_root_path / r["rel_path"]
        if p.exists():
            files.append((p, r["filename"]))
            nodi_coinvolti.add(r["nid"])
            id_accettati.append(r["id"])
    if not files:
        raise HTTPException(status_code=404, detail="Nessun file da scaricare")
    record_stat("zip_select", str(len(files)))
    for nid in nodi_coinvolti:
        record_node_stat(nid, "zip")
    # Stessa chiave di lock di zip_select: una selezione condivisa e una
    # selezione diretta con lo stesso identico insieme di foto condividono
    # il lucchetto, evitando doppia compressione simultanea dello stesso
    # contenuto.
    try:
        return _risposta_zip(files, "selezione.zip", segnale=segnale,
                             chiave_lock=chiave_selezione(id_accettati))
    except ArchivioGiaInPreparazione as e:
        return _risposta_zip_occupato(str(e), segnale)
