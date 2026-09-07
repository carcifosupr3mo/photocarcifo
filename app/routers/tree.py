"""Router di navigazione ad ALBERO: home, nodi, ricerca, album privati.

I nodi nascosti (hidden=1) non compaiono mai nella navigazione pubblica,
nemmeno per gli amministratori: restano gestibili solo dal pannello.
Le cartelle con molte foto vengono impaginate per non appesantire il browser.
"""
import random

from fastapi import APIRouter, Request, Query, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from datetime import datetime, timedelta, timezone

from itsdangerous import URLSafeTimedSerializer, BadSignature

from .. import lingue, numeri
from ..config import get_settings
from ..database import (get_db, log_event, registra_ricerca,
                        record_node_stat, record_stat_bufferizzato,
                        sottoalbero_like)
from ..security import verify_password
from ..deps import get_current_user
from ..templating import templates

router = APIRouter()

_UNLOCK_COOKIE = "pc_unlock"

# Durate proposte per i link di condivisione. La chiave "0" significa
# nessuna scadenza.
DURATE_LINK = {"7": 7, "30": 30, "90": 90, "180": 180, "365": 365, "0": None}


def calcola_scadenza(giorni):
    """Data di scadenza in formato ISO, oppure None per un link illimitato."""
    g = DURATE_LINK.get(str(giorni).strip())
    if not g:
        return None
    return (datetime.now(timezone.utc) + timedelta(days=g)).isoformat()


def scaduto(expires_at) -> bool:
    """Vero se il link non e' piu' valido.

    In caso di data illeggibile si preferisce lasciare il link attivo:
    meglio un accesso in piu' che chiudere fuori un cliente per un errore
    di formato."""
    if not expires_at:
        return False
    try:
        dt = datetime.fromisoformat(expires_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) > dt
    except (ValueError, TypeError):
        return False


def giorni_rimasti(expires_at):
    """Quanti giorni mancano alla scadenza, None se il link e' illimitato."""
    if not expires_at:
        return None
    try:
        dt = datetime.fromisoformat(expires_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = dt - datetime.now(timezone.utc)
        if delta.total_seconds() <= 0:
            return 0
        return int(delta.total_seconds() // 86400) + (1 if delta.seconds % 86400 else 0)
    except (ValueError, TypeError):
        return None
PAGE_SIZE = 120

# Data dell'ultima fotografia contenuta nell'album o nelle sue sottocartelle:
# e' il momento dello scatto, piu' affidabile della data in cui la cartella
# e' stata letta dal NAS. E' precalcolata dalla scansione
# nella colonna nodes.data_foto. Ricavarla al volo con una sottoquery su tutte
# le fotografie costava una sessantina di millisecondi su ogni pagina.
_DATA_ALBUM = "data_foto"

ORDINI_ALBUM = {
    "recenti": f"COALESCE({_DATA_ALBUM}, 0) DESC",
    "vecchi": f"COALESCE({_DATA_ALBUM}, 9999999999) ASC",
    "nome": "title COLLATE NOCASE ASC",
    "foto": "total_media DESC",
}
ORDINE_PREDEFINITO = "recenti"


def _is_admin(request: Request) -> bool:
    u = get_current_user(request)
    return bool(u and u.get("is_admin"))


def _unlock_serializer():
    return URLSafeTimedSerializer(get_settings().secret_key, salt="node-unlock")


def _nodi_sbloccati(request) -> list:
    """Album privati che questo visitatore ha diritto di vedere."""
    token = request.cookies.get(_UNLOCK_COOKIE)
    if not token:
        return []
    try:
        return _unlock_serializer().loads(token, max_age=86400).get("nodes", [])
    except Exception:
        return []


def _is_unlocked(request, node_id) -> bool:
    """Vero se il visitatore ha gia' sbloccato questo nodo con la password."""
    token = request.cookies.get(_UNLOCK_COOKIE)
    if not token:
        return False
    try:
        return node_id in _unlock_serializer().loads(token, max_age=86400).get("nodes", [])
    except (BadSignature, Exception):
        return False


def _sotto_nodi(conn, rel_path):
    """Identificativi dell'album e di tutte le sue sottocartelle.

    Chi riceve un link deve poter vedere anche le anteprime delle cartelle
    interne, altrimenti la galleria resterebbe piena di riquadri vuoti."""
    rows = conn.execute(
        "SELECT id FROM nodes WHERE rel_path=? OR rel_path LIKE ? ESCAPE '\\'",
        (rel_path, sottoalbero_like(rel_path))).fetchall()
    return [r["id"] for r in rows]


def _lasciapassare_solo(ids):
    """Lasciapassare valido soltanto per questi album.

    Non accumula gli accessi precedenti: chi apre il link dell'album A
    deve vedere A e nient'altro, anche dopo aver visitato altri link."""
    return _unlock_serializer().dumps({"nodes": [int(i) for i in ids]})


def _cover(conn, node):
    """Fotografia che rappresenta una cartella nelle griglie.

    Si cerca in tre passi, dal piu' economico al piu' costoso.

    Prima la copertina scelta a mano dal pannello, se c'e'. Poi una
    fotografia contenuta direttamente in questa cartella: e' una lettura
    sull'indice di node_id, immediata, e copre le 112 gallerie di gare, che
    sono la stragrande maggioranza. Solo per le cartelle che contengono
    unicamente altre cartelle (le discipline, gli anni) si scende nel
    sottoalbero.

    Il terzo passo e' quello caro: il confronto con LIKE sul percorso non
    puo' usare nessun indice, quindi SQLite legge tutte le 48.000
    fotografie e le ordina in una tabella temporanea. Misurato: 8,5
    millisecondi ogni volta, moltiplicati per ogni cartella mostrata in
    pagina. Facendolo solo per le due dozzine di cartelle-contenitore
    invece che per tutte, la pagina delle novita' e' passata da 14 a meno
    di un millisecondo.
    """
    if node["cover_media_id"]:
        # Si controlla che la fotografia scelta a mano esista ancora: se e'
        # stata cancellata o spostata nel cestino, il riferimento resta nel
        # database e la vetrina mostrerebbe un riquadro rotto. In quel caso
        # si torna alla copertina automatica, come se non fosse mai stata
        # scelta: meglio una foto diversa che nessuna foto.
        viva = conn.execute("SELECT 1 FROM media WHERE id=?",
                            (node["cover_media_id"],)).fetchone()
        if viva:
            return node["cover_media_id"]
    # kind ASC: 'image' viene prima di 'video', cosi' si preferisce una
    # fotografia a un fotogramma di filmato. Era gia' cosi' prima.
    riga = conn.execute(
        "SELECT id FROM media WHERE node_id=? "
        "ORDER BY kind ASC, sort_order, filename LIMIT 1",
        (node["id"],)).fetchone()
    if riga:
        return riga["id"]
    row = conn.execute(
        "SELECT m.id FROM media m JOIN nodes n ON n.id=m.node_id "
        "WHERE n.rel_path=? OR n.rel_path LIKE ? ESCAPE '\\' "
        "ORDER BY m.kind ASC, m.sort_order, m.filename LIMIT 1",
        (node["rel_path"], sottoalbero_like(node["rel_path"]))).fetchone()
    return row["id"] if row else None


def _categorie_consentite(conn, sbloccati):
    """Categorie superiori degli album che il visitatore ha sbloccato.

    Servono per far ricomparire la cartella degli shooting privati a chi
    possiede un link, mostrandogli pero' soltanto il proprio album."""
    if not sbloccati:
        return []
    consentiti = [int(x) for x in sbloccati]
    segnaposto = ",".join("?" * len(consentiti))
    righe = conn.execute(
        f"SELECT DISTINCT parent_id FROM nodes WHERE id IN ({segnaposto}) "
        f"AND parent_id IS NOT NULL", consentiti).fetchall()
    return [r["parent_id"] for r in righe]


def _cover_molteplici(conn, nodes):
    """Copertine di piu' nodi in blocco, invece di una query a nodo.

    Stessi tre passi di _cover(), ma fatti una volta sola su tutti i nodi
    invece che uno alla volta: su una pagina con decine di cartelle era il
    principale N+1 della navigazione.
    """
    risultato = {}
    da_cercare_diretta = []
    # Le copertine scelte a mano si controllano tutte insieme, con una sola
    # domanda al database invece di una per album: quelle che puntano a una
    # fotografia non piu' esistente (cancellata, o finita nel cestino)
    # ricadono nella scelta automatica come se non fossero mai state fatte.
    scelte = [n["cover_media_id"] for n in nodes if n["cover_media_id"]]
    vive = set()
    if scelte:
        segnaposto = ",".join("?" * len(scelte))
        vive = {r["id"] for r in conn.execute(
            f"SELECT id FROM media WHERE id IN ({segnaposto})", scelte)}
    for n in nodes:
        if n["cover_media_id"] and n["cover_media_id"] in vive:
            risultato[n["id"]] = n["cover_media_id"]
        else:
            da_cercare_diretta.append(n)

    if da_cercare_diretta:
        ids = [n["id"] for n in da_cercare_diretta]
        segnaposto = ",".join("?" * len(ids))
        righe = conn.execute(
            f"SELECT node_id, id FROM media WHERE node_id IN ({segnaposto}) "
            f"ORDER BY kind ASC, sort_order, filename", ids).fetchall()
        trovate = {}
        for r in righe:
            trovate.setdefault(r["node_id"], r["id"])
        rimasti = []
        for n in da_cercare_diretta:
            if n["id"] in trovate:
                risultato[n["id"]] = trovate[n["id"]]
            else:
                rimasti.append(n)
    else:
        rimasti = []

    # Il terzo passo, quello caro con LIKE, resta per nodo: riguarda solo
    # le cartelle-contenitore (poche per pagina), non merita un'unione.
    for n in rimasti:
        row = conn.execute(
            "SELECT m.id FROM media m JOIN nodes n2 ON n2.id=m.node_id "
            "WHERE n2.rel_path=? OR n2.rel_path LIKE ? ESCAPE '\\' "
            "ORDER BY m.kind ASC, m.sort_order, m.filename LIMIT 1",
            (n["rel_path"], sottoalbero_like(n["rel_path"]))).fetchone()
        risultato[n["id"]] = row["id"] if row else None
    return risultato


def _child_nodes(conn, parent_id, show_private=False, sbloccati=None,
                 ordine=ORDINE_PREDEFINITO):
    """Sottocartelle visibili al visitatore.

    Gli album riservati non compaiono mai nella navigazione pubblica,
    nemmeno per chi ne possiede uno: l'unico modo per raggiungerli e' il
    link ricevuto. L'ordine predefinito mostra per primi i lavori piu'
    recenti, in base alla data delle fotografie contenute."""
    q = ("SELECT id, slug, title, rel_path, cover_media_id, is_private, "
         "access_token, total_media FROM nodes WHERE ")
    q += "parent_id IS NULL" if parent_id is None else "parent_id=?"
    q += " AND hidden=0"
    parametri = [] if parent_id is None else [parent_id]

    if not show_private:
        propri = [int(x) for x in (sbloccati or [])]
        if propri:
            segnaposto = ",".join("?" * len(propri))
            q += f" AND (is_private=0 OR id IN ({segnaposto}))"
            parametri += propri
        else:
            q += " AND is_private=0"

    criterio = ORDINI_ALBUM.get(ordine, ORDINI_ALBUM[ORDINE_PREDEFINITO])
    q += f" ORDER BY {criterio}, title COLLATE NOCASE"
    rows = conn.execute(q, tuple(parametri)).fetchall()
    copertine = _cover_molteplici(conn, rows)
    out = []
    for r in rows:
        d = dict(r)
        d["cover"] = copertine.get(r["id"])
        out.append(d)
    return out


def _media_count(conn, node_id) -> int:
    return conn.execute("SELECT COUNT(*) c FROM media WHERE node_id=?",
                        (node_id,)).fetchone()["c"]


def _node_media(conn, node_id, offset=0, limit=PAGE_SIZE):
    rows = conn.execute(
        "SELECT id, kind, filename, width, height, duration FROM media "
        "WHERE node_id=? ORDER BY kind DESC, sort_order, filename LIMIT ? OFFSET ?",
        (node_id, limit, offset)).fetchall()
    return [dict(r) for r in rows]


def _breadcrumb(conn, node, admin=False, permessi=None):
    """Percorso dalla radice fino a questo nodo.

    Prima risaliva ai genitori con una query sequenziale per livello
    (SELECT ... WHERE id=? ripetuta finche' non si arrivava alla radice).
    Con una CTE ricorsiva si risale l'intera catena in una sola query;
    l'ordine si sistema poi in Python.

    Fino al 26/08/2026 ogni antenato riservato veniva restituito con
    titolo e access_token cosi' com'erano nel database, e il template li
    mostrava sempre come link cliccabile — indipendentemente dal fatto
    che il visitatore avesse il DIRITTO di vedere quell'antenato. Risultato
    concreto: aprendo l'album "Giada" con un link diretto, il breadcrumb
    mostrava comunque il nome vero e un link funzionante verso "Shooting
    privati" (il genitore, con un proprio access_token distinto), e
    cliccandolo si otteneva un nuovo lasciapassare per l'intero ramo —
    non un problema di CSS, un secondo link valido esposto dove non
    doveva starci.

    Ora ogni riga porta anche `sbloccato`: vero se il visitatore ha
    diritto di vedere quell'antenato per davvero (admin, o l'id e' fra i
    permessi calcolati per QUESTA richiesta — la stessa lista gia' usata
    per filtrare figli/ricerca, non una nuova logica). Il template non fa
    piu' nessuna scelta di sicurezza da solo: si limita a leggere questo
    campo. Un antenato riservato non sbloccato mostra SOLO l'etichetta
    neutra passata dal chiamante (mai il titolo vero, mai un link),
    esattamente come una cartella-contenitore senza nome proprio.
    """
    righe = conn.execute(
        "WITH RECURSIVE catena(id, parent_id, slug, title, is_private, access_token) AS ("
        "  SELECT id, parent_id, slug, title, is_private, access_token FROM nodes WHERE id=?"
        "  UNION ALL"
        "  SELECT n.id, n.parent_id, n.slug, n.title, n.is_private, n.access_token"
        "  FROM nodes n JOIN catena c ON n.id = c.parent_id"
        ") SELECT id, slug, title, is_private, access_token FROM catena",
        (node["id"],)).fetchall()
    permessi_set = {int(x) for x in (permessi or [])}
    chain = []
    for r in righe:
        sbloccato = bool(admin) or not r["is_private"] or r["id"] in permessi_set
        chain.append({
            "slug": r["slug"],
            "title": r["title"] if sbloccato else None,
            "is_private": r["is_private"],
            "access_token": r["access_token"] if sbloccato else None,
            "sbloccato": sbloccato,
        })
    return list(reversed(chain))


@router.get("/", response_class=HTMLResponse)
def home(request: Request, ordine: str = Query(ORDINE_PREDEFINITO),
         q: str = Query("", max_length=100), page: int = Query(1, ge=1)):
    admin = _is_admin(request)
    if ordine not in ORDINI_ALBUM:
        ordine = ORDINE_PREDEFINITO
    with get_db() as conn:
        categories = _child_nodes(conn, None, show_private=admin,
                                  sbloccati=_nodi_sbloccati(request),
                                  ordine=ordine)
    # I testi della pagina iniziale arrivano da lingue.py, in cinque lingue.
    # Prima si passavano anche due valori presi dalle impostazioni, che pero'
    # il modello non guardava piu': erano rimasti li' a far credere che
    # scrivendo qualcosa nel pannello la home cambiasse.
    contesto = {"categories": categories, "is_admin": admin, "ordine": ordine}
    # Se arriva una ricerca (?q=...), la home mostra gli stessi risultati che
    # dava il vecchio indirizzo "/search", ora un semplice redirect qui.
    # Senza "q" il contesto resta quello di sempre: nessuna ricerca attiva.
    q = q.strip()
    if q:
        risultato = _esegui_ricerca(request, q, page, admin)
        contesto.update({
            "risultati_ricerca": risultato["results"],
            "foto_ricerca": risultato["foto"],
            "numero_ricerca": risultato["numero"],
            "totale_ricerca": risultato["totale"],
            "page_ricerca": risultato["page"],
            "pagine_ricerca": risultato["pagine"],
            "q": risultato["query"],
        })
    return templates.TemplateResponse(request, "public/home.html", contesto)


def _foto_anteprima(conn, node, media, children):
    """Fotografia da mostrare quando il link viene incollato in una chat.

    Gli album di foto usano la prima immagine della pagina. Le cartelle che
    contengono solo altre cartelle (BMX, MOTO, gli anni) non hanno immagini
    proprie: prima non mostravano niente e il link usciva nudo.

    Per queste si pesca a caso in tutto quello che contengono, non solo fra
    le sottocartelle di primo livello: BMX ne ha due sole (2025 e 2026) e
    l'anteprima avrebbe alternato sempre le stesse due fotografie, mentre
    piu' in basso ci sono decine di gare. Si sceglie a caso una cartella fra
    tutte le discendenti e si usa la sua copertina: due interrogazioni
    piccole invece di pescare fra decine di migliaia di fotografie.
    """
    if media:
        return media[0]["id"]
    # Solo le cartelle DENTRO questa, mai questa stessa: cercare la
    # copertina del nodo di partenza vorrebbe dire ordinare tutte le
    # fotografie del sottoalbero, e su BMX sono oltre quarantamila. La
    # pagina ci metteva cinque secondi e i lettori di anteprima delle chat,
    # che aspettano pochi istanti, rinunciavano senza mostrare nulla.
    righe = conn.execute(
        "SELECT id, cover_media_id FROM nodes "
        "WHERE rel_path LIKE ? ESCAPE '\\' AND hidden=0 AND is_private=0",
        (sottoalbero_like(node["rel_path"]),)).fetchall()
    if not righe:
        # ripiego: le copertine delle sottocartelle gia' in pagina
        copertine = [c["cover"] for c in (children or []) if c.get("cover")]
        return random.choice(copertine) if copertine else None
    # Qualche tentativo: una cartella potrebbe contenere solo altre cartelle.
    # Si guardano le fotografie di quella cartella soltanto, non di tutto
    # cio' che contiene: una lettura diretta sull'indice, immediata. Le
    # candidate senza copertina propria si controllano in una sola query
    # con IN(...) invece che una per candidata.
    candidate = random.sample(list(righe), min(6, len(righe)))
    da_cercare = []
    for candidata in candidate:
        if candidata["cover_media_id"]:
            return candidata["cover_media_id"]
        da_cercare.append(candidata["id"])
    if da_cercare:
        segnaposto = ",".join("?" * len(da_cercare))
        trovate = {}
        for r in conn.execute(
                f"SELECT node_id, id FROM media WHERE node_id IN ({segnaposto}) "
                f"AND kind='image' ORDER BY sort_order, filename", da_cercare).fetchall():
            trovate.setdefault(r["node_id"], r["id"])
        for node_id in da_cercare:
            if node_id in trovate:
                return trovate[node_id]
    return None


def _e_apertura_vera(request, page: int) -> bool:
    """Vero se questa e' una vera apertura dell'album e non solo un
    cambio di pagina o di ordinamento all'interno dello stesso album.

    Sfoglia la pagina 2, o cambia l'ordinamento con la stessa richiesta
    GET su questo stesso indirizzo: il referer, in quel caso, e' la stessa
    pagina con solo la query string diversa. Si conta come apertura solo
    la prima pagina raggiunta da un referer diverso da questo stesso
    percorso (o senza referer, come un link incollato o un preferito).
    """
    if page != 1:
        return False
    provenienza = request.headers.get("referer", "")
    if not provenienza:
        return True
    return request.url.path not in provenienza


def _render_node(request, node, admin, via_token, page=1, ordine=ORDINE_PREDEFINITO,
                 gia_permessi=None):
    if not admin and _e_apertura_vera(request, page):
        record_node_stat(node["id"], "open")
    with get_db() as conn:
        # gia_permessi: album che questo visitatore ha diritto di vedere
        # adesso, anche se il lasciapassare non e' ancora nel suo browser.
        # Serve alla prima apertura di un link riservato: il permesso viene
        # consegnato insieme a questa stessa pagina, quindi al momento di
        # costruirla il visitatore non ce l'ha ancora.
        permessi = list(_nodi_sbloccati(request)) + list(gia_permessi or [])
        children = _child_nodes(conn, node["id"], show_private=admin,
                                sbloccati=permessi,
                                ordine=ordine)
        total = _media_count(conn, node["id"])
        pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        page = min(max(1, page), pages)
        media = _node_media(conn, node["id"], offset=(page - 1) * PAGE_SIZE)
        crumbs = _breadcrumb(conn, node, admin=admin, permessi=permessi)
        og_media = _foto_anteprima(conn, node, media, children)
    record_stat_bufferizzato("view_node", node["slug"])
    return templates.TemplateResponse(request, "public/node.html", {"node": dict(node), "children": children,
        "media": media, "crumbs": crumbs, "is_admin": admin, "via_token": via_token,
        "page": page, "pages": pages, "total_media": total, "page_size": PAGE_SIZE,
        "ordine": ordine, "og_media": og_media,
        "is_admin_csrf": (get_current_user(request) or {}).get("csrf", "")})


@router.get("/n/{slug}", response_class=HTMLResponse)
def public_node(request: Request, slug: str, page: int = Query(1, ge=1),
                ordine: str = Query(ORDINE_PREDEFINITO)):
    admin = _is_admin(request)
    with get_db() as conn:
        node = conn.execute("SELECT * FROM nodes WHERE slug=?", (slug,)).fetchone()
        if not node:
            raise HTTPException(status_code=404, detail="Cartella non trovata")
        if not admin:
            sbloccati = _nodi_sbloccati(request)
            permesse = _categorie_consentite(conn, sbloccati)
            # una cartella nascosta si apre solo se contiene un album
            # che questo visitatore ha sbloccato con il proprio link
            if node["hidden"] and node["id"] not in permesse:
                raise HTTPException(status_code=404, detail="Cartella non trovata")
            propri = [int(x) for x in sbloccati]
            if node["is_private"] and node["id"] not in propri:
                raise HTTPException(status_code=404, detail="Cartella non trovata")
    if ordine not in ORDINI_ALBUM:
        ordine = ORDINE_PREDEFINITO
    return _render_node(request, node, admin, via_token=False, page=page,
                        ordine=ordine)


@router.get("/p/{token}", response_class=HTMLResponse)
def private_node(request: Request, token: str, page: int = Query(1, ge=1),
                 ordine: str = Query(ORDINE_PREDEFINITO)):
    admin = _is_admin(request)
    with get_db() as conn:
        node = conn.execute(
            "SELECT * FROM nodes WHERE access_token=? AND is_private=1", (token,)).fetchone()
    if not node:
        raise HTTPException(status_code=404, detail="Cartella non trovata")
    if not admin and scaduto(node["expires_at"]):
        return templates.TemplateResponse(request, "public/node_scaduto.html", {"node": dict(node)}, status_code=410)
    if node["password_hash"] and not admin and not _is_unlocked(request, node["id"]):
        return templates.TemplateResponse(request, "public/node_password.html", {"node": dict(node), "error": None})
    if ordine not in ORDINI_ALBUM:
        ordine = ORDINE_PREDEFINITO
    # Gli album contenuti in questo, calcolati prima di disegnare la pagina.
    #
    # Un album riservato che contiene solo altre cartelle (le due sessioni
    # di uno shooting, per dire) alla prima apertura risultava vuoto: il
    # lasciapassare viene consegnato insieme a questa risposta, quindi
    # mentre la pagina si costruiva il visitatore non l'aveva ancora e le
    # sottocartelle, essendo riservate, venivano nascoste anche a lui.
    # Bastava ricaricare e comparivano, ma il cliente vedeva una pagina
    # vuota e pensava che il link fosse sbagliato.
    with get_db() as conn:
        ids = _sotto_nodi(conn, node["rel_path"])
    risposta = _render_node(request, node, admin, via_token=True, page=page,
                            ordine=ordine, gia_permessi=ids)
    # Il lasciapassare si rinnova solo quando il link viene aperto
    # direttamente. Se il visitatore ci arriva navigando dall'interno di
    # un altro album riservato, il permesso resta quello che aveva: senza
    # questo controllo un semplice collegamento interno sostituirebbe il
    # suo accesso con quello di un altro cliente.
    provenienza = request.headers.get("referer", "")
    arriva_da_dentro = "/p/" in provenienza and token not in provenienza
    if not admin and not arriva_da_dentro:
        # chi ha il link puo' vedere le anteprime di questo album e delle
        # sue sottocartelle: senza questo permesso le foto non caricano
        risposta.set_cookie(_UNLOCK_COOKIE, _lasciapassare_solo(ids),
                            max_age=86400, httponly=True, samesite="lax",
                            secure=True, path="/")
    return risposta


@router.post("/p/{token}/unlock", response_class=HTMLResponse)
def private_unlock(request: Request, token: str, password: str = Form(...)):
    with get_db() as conn:
        node = conn.execute(
            "SELECT * FROM nodes WHERE access_token=? AND is_private=1", (token,)).fetchone()
    if not node:
        raise HTTPException(status_code=404, detail="Cartella non trovata")
    if not node["password_hash"] or not verify_password(password, node["password_hash"]):
        log_event("WARNING", "auth", f"Password nodo errata: {node['slug']}")
        errore = lingue.traduci("pwd.errore", lingue.lingua_di(request))
        return templates.TemplateResponse(request, "public/node_password.html", {"node": dict(node), "error": errore},
            status_code=status.HTTP_401_UNAUTHORIZED)
    with get_db() as conn:
        ids = _sotto_nodi(conn, node["rel_path"])
    cookie = _lasciapassare_solo(ids)
    resp = RedirectResponse(url=f"/p/{token}", status_code=status.HTTP_303_SEE_OTHER)
    resp.set_cookie(_UNLOCK_COOKIE, cookie, max_age=86400,
                    httponly=True, samesite="lax", secure=True, path="/")
    return resp


# Fotografie per pagina nella ricerca per numero. Non e' un tetto: le altre
# si raggiungono con le pagine successive, cosi' anche un numero usato in
# migliaia di scatti resta consultabile per intero.
FOTO_PER_PAGINA = 120


def _parole_ricerca(q: str) -> list:
    """Divide la query in parole significative, senza doppioni e senza
    frammenti vuoti (spazi multipli, tabulazioni...). "raduno manno" e
    "manno   raduno" producono la stessa lista, in ordine di prima
    comparsa (l'ordine qui non conta per il match, solo per stabilita')."""
    viste = []
    for pezzo in q.split():
        p = pezzo.strip()
        if p and p not in viste:
            viste.append(p)
    return viste


def _cerca_cartelle(conn, request, q: str, admin: bool, includi_hidden: bool = False) -> list:
    """Album e cartelle che contengono TUTTE le parole della query.

    Fino al 26/08/2026 la ricerca cercava la query intera come UNA sola
    frase (LIKE '%raduno manno%'): "raduno manno" non trovava "Raduno Zona
    Industriale Manno" perche' le due parole, nel titolo vero, non stanno
    una attaccata all'altra. Ora ogni parola e' una condizione AND
    indipendente (LIKE '%raduno%' AND LIKE '%manno%'), verificata sugli
    stessi tre campi di prima: ordine delle parole e distanza fra loro nel
    titolo non contano piu', solo che ci siano tutte.

    includi_hidden: normalmente le cartelle nascoste (hidden=1) restano
    fuori dalla ricerca, anche per l'amministratore, come nel resto della
    navigazione pubblica. Il pannello admin ha bisogno di ritrovarle
    comunque (sono gestibili solo da li'): passa True solo dal chiamante
    admin-aware, mai dalla ricerca pubblica.
    """
    parole = _parole_ricerca(q)
    if not parole:
        return []
    # I jolly di LIKE vanno neutralizzati parola per parola: senza, cercare
    # "%" o "_" restituirebbe l'intero archivio.
    def fuggi(parola):
        return parola.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    condizioni = []
    parametri = []
    for parola in parole:
        like = f"%{fuggi(parola)}%"
        condizioni.append(
            "(title LIKE ? ESCAPE '\\' OR name LIKE ? ESCAPE '\\' "
            "OR rel_path LIKE ? ESCAPE '\\')")
        parametri += [like, like, like]
    dove_parole = " AND ".join(condizioni)

    # Per il ranking (frase esatta / nome esatto) serve anche la query
    # intera cosi' come scritta, non le parole separate.
    frase = f"%{fuggi(q.strip())}%"

    # parent_path si calcola qui in SQL invece che rifacendo rel_path.split
    # in Python per ogni riga: la parte prima dell'ultima "/" (o stringa
    # vuota se non c'e' nessuna "/"), con gli underscore gia' sostituiti da
    # spazi — sostituzione valida sull'intera stringa perche' "/" non e'
    # toccato dal REPLACE.
    base = ("SELECT id, slug, title, rel_path, depth, cover_media_id, "
            "is_private, hidden, access_token, total_media, "
            "REPLACE(CASE WHEN instr(rel_path, '/') > 0 "
            "  THEN substr(rel_path, 1, length(rel_path) - length(name) - 1) "
            "  ELSE '' END, '_', ' ') AS parent_path_raw, "
            # Rango: 0 = nome identico alla query, 1 = la frase intera
            # compare nel titolo, 2 = tutte le parole compaiono nel solo
            # titolo (anche sparse), 3 = le parole sono sparse fra
            # titolo/percorso (il caso base, garantito dal WHERE).
            "CASE WHEN lower(title) = lower(?) THEN 0 "
            "  WHEN title LIKE ? ESCAPE '\\' THEN 1 "
            "  WHEN " + " AND ".join(
                "title LIKE ? ESCAPE '\\'" for _ in parole) + " THEN 2 "
            "  ELSE 3 END AS rango "
            "FROM nodes "
            f"WHERE {dove_parole}" + ("" if includi_hidden else " AND hidden=0"))
    parametri_rango = [q.strip(), frase] + [f"%{fuggi(p)}%" for p in parole]
    parametri = parametri_rango + parametri
    if not admin:
        consentiti = [int(x) for x in _nodi_sbloccati(request)]
        if consentiti:
            segnaposto = ",".join("?" * len(consentiti))
            base += f" AND (is_private=0 OR id IN ({segnaposto}))"
            parametri += consentiti
        else:
            base += " AND is_private=0"
    base += " ORDER BY rango, depth, sort_order, title LIMIT 300"
    righe = conn.execute(base, parametri).fetchall()
    copertine = _cover_molteplici(conn, righe)
    trovati = []
    for r in righe:
        d = dict(r)
        d.pop("rango", None)
        d["cover"] = copertine.get(r["id"])
        d["parent_path"] = d.pop("parent_path_raw").replace("/", " / ")
        trovati.append(d)
    return trovati


# Programmi automatici che passano lo stesso di qui, nonostante robots.txt
# chieda di non farlo. Le loro ricerche non sono domande di nessuno e
# sporcherebbero il registro.
_AUTOMI = ("bot", "spider", "crawl", "slurp", "curl", "wget", "python-requests",
           "headless", "monitor", "preview", "facebookexternalhit")


def _annota_ricerca(request, q, numero, risultati, admin):
    """Registra la ricerca, saltando chi non e' un visitatore vero.

    Le ricerche dell'amministratore non contano: sarebbero soprattutto le
    prove fatte mentre si sistema l'archivio, e coprirebbero le domande
    delle persone, che sono l'unica cosa per cui questo registro esiste.
    """
    if admin:
        return
    agente = (request.headers.get("user-agent") or "").lower()
    if not agente or any(s in agente for s in _AUTOMI):
        return
    registra_ricerca(q, numero, risultati)


def _esegui_ricerca(request, q: str, page: int, admin: bool) -> dict:
    """Una sola ricerca per fotografie e cartelle.

    Chi scrive il proprio numero di tabella trova le proprie foto; chi
    scrive delle parole trova le cartelle. Le due cose non si escludono:
    anche quando si scrive un numero si cercano lo stesso le cartelle, cosi'
    chi cerca "2026" trova gli album di quell'anno invece di ricevere un
    "nessuna fotografia" che sembra un guasto.

    Condivisa fra l'indirizzo storico "/search" (ora un redirect) e la home,
    che puo' mostrare gli stessi risultati senza cambiare pagina.
    """
    q = q.strip()
    numero = numeri.leggi_query(q) if q else None
    foto, totale, pagine, results = [], 0, 1, []

    if q:
        with get_db() as conn:
            if numero:
                consentite = numeri.cartelle_visibili(
                    conn, sbloccati=_nodi_sbloccati(request), admin=admin)
                totale = numeri.conta_foto(conn, numero, consentite)
                pagine = max(1, (totale + FOTO_PER_PAGINA - 1) // FOTO_PER_PAGINA)
                page = min(page, pagine)
                foto = numeri.cerca_foto(conn, numero, consentite,
                                         limite=FOTO_PER_PAGINA,
                                         salta=(page - 1) * FOTO_PER_PAGINA)
            results = _cerca_cartelle(conn, request, q, admin)
        _annota_ricerca(request, q, numero, totale + len(results), admin)

    return {"results": results, "foto": foto,
        "numero": numero if foto or not results else None,
        "totale": totale, "page": page if foto else 1,
        "pagine": pagine, "query": q, "is_admin": admin}


@router.get("/search", response_class=HTMLResponse)
def search(request: Request, q: str = Query("", max_length=100),
           page: int = Query(1, ge=1)):
    """Indirizzo storico della ricerca: ora rimanda alla home, che sa fare
    la stessa cosa senza una pagina a parte."""
    from urllib.parse import urlencode
    parametri = {}
    if q:
        parametri["q"] = q
    if page != 1:
        parametri["page"] = page
    destinazione = "/" + (f"?{urlencode(parametri)}" if parametri else "")
    return RedirectResponse(url=destinazione, status_code=status.HTTP_302_FOUND)


# Quante gallerie mostrare fra le novita'. Trenta e' circa una stagione di
# gare: abbastanza per non tagliare fuori chi guarda una volta al mese,
# poche abbastanza da restare una pagina sola.
NOVITA = 30


def _ultime_gallerie(conn, quante=NOVITA):
    """Le gallerie con le fotografie piu' recenti.

    Si ordina per data dello scatto e non per data di caricamento: gli
    album arrivano sul sito a gruppi, spesso a giorni di distanza dalla
    gara, e ordinandoli per caricamento una gara di marzo caricata a
    giugno comparirebbe come la novita' del giorno.

    Solo cartelle che contengono fotografie: quelle che ne contengono solo
    altre (BMX, MOTO, gli anni) non sono una novita', ci stanno sempre.
    """
    righe = conn.execute(
        "SELECT id, slug, title, rel_path, cover_media_id, total_media, "
        "       data_foto, depth "
        "FROM nodes WHERE is_private=0 AND hidden=0 AND total_media>0 "
        "  AND direct_media>0 AND data_foto IS NOT NULL "
        "ORDER BY data_foto DESC LIMIT ?", (quante,)).fetchall()
    copertine = _cover_molteplici(conn, righe)
    fuori = []
    for r in righe:
        d = dict(r)
        d["cover"] = copertine.get(r["id"])
        parti = r["rel_path"].split("/")[:-1]
        d["dove"] = " / ".join(p.replace("_", " ") for p in parti)
        d["quando"] = (datetime.fromtimestamp(r["data_foto"], timezone.utc)
                       if r["data_foto"] else None)
        fuori.append(d)
    return fuori


@router.get("/novita", response_class=HTMLResponse)
def novita(request: Request):
    """Le ultime gallerie pubblicate, in una pagina sola.

    Senza contatti e senza newsletter, questa pagina e il feed che le sta
    dietro sono l'unico modo che ha una persona per sapere che sono uscite
    fotografie nuove senza dover ricontrollare a mano ogni cartella.
    """
    with get_db() as conn:
        gallerie = _ultime_gallerie(conn)
    return templates.TemplateResponse(request, "public/novita.html", {"is_admin": _is_admin(request),
        "gallerie": gallerie})


@router.get("/chi-sono", response_class=HTMLResponse)
def chi_sono(request: Request):
    """Pagina di presentazione.

    I numeri dell'archivio si contano al momento invece di scriverli a mano:
    una pagina che dice "oltre 10.000 fotografie" invecchia il giorno dopo,
    e correggerla a ogni gara non se lo ricorda nessuno. Si contano solo le
    cartelle pubbliche: gli shooting riservati non riguardano i visitatori.
    """
    with get_db() as conn:
        riga = conn.execute(
            "SELECT (SELECT COUNT(*) FROM media m JOIN nodes n ON n.id=m.node_id "
            "        WHERE n.is_private=0 AND n.hidden=0 AND m.kind='image') foto, "
            "       (SELECT COUNT(*) FROM nodes WHERE is_private=0 AND hidden=0 "
            "        AND total_media>0) gallerie, "
            "       (SELECT COUNT(*) FROM nodes WHERE parent_id IS NULL "
            "        AND is_private=0 AND hidden=0) discipline, "
            "       (SELECT MIN(mtime) FROM media) prima").fetchone()
    numeri_archivio = dict(riga)
    prima = numeri_archivio.pop("prima", None)
    numeri_archivio["dal"] = (
        datetime.fromtimestamp(prima, timezone.utc).year if prima else None)
    return templates.TemplateResponse(request, "public/chi_sono.html", {"is_admin": _is_admin(request),
        "numeri": numeri_archivio})


@router.get("/privacy", response_class=HTMLResponse)
def privacy(request: Request):
    """Condizioni d'uso, copyright e informativa sui cookie."""
    return templates.TemplateResponse(request, "public/privacy.html", {"is_admin": _is_admin(request)})
