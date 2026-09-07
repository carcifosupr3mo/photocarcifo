"""Dashboard amministratore - versione base compatibile col modello ad albero."""
import json
import shutil
import subprocess
from datetime import datetime

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

# Script che fa scansione + miniature + numeri in un colpo solo: per chi ha
# appena caricato foto nuove sul Synology e non vuole aspettare i timer
# (scansione ogni 10 minuti, numeri ogni 9, miniature solo di notte).
_SCRIPT_AGGIUNTA_FOTO = "/opt/photocarcifo/script/photocarcifo-aggiunta-foto.sh"


def _aggiunta_foto_in_corso() -> bool:
    """Vero se lo script e' gia' in esecuzione, per non farne partire due insieme."""
    try:
        return subprocess.run(
            ["pgrep", "-f", _SCRIPT_AGGIUNTA_FOTO],
            capture_output=True, timeout=5,
        ).returncode == 0
    except Exception:
        return False


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
        "ocr_lavoro": ocr.stato_lavoro(),
        "aggiunta_foto_in_corso": _aggiunta_foto_in_corso()})


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


@router.post("/maintenance/aggiunta-foto")
def do_aggiunta_foto(request: Request, csrf_token: str = Form(...),
                     user: dict = Depends(require_admin_api)):
    """Scansione + miniature + numeri in un colpo solo, per il materiale
    appena caricato sul Synology.

    Gira in un processo staccato, non nel worker web: le miniature da sole
    possono richiedere minuti e la richiesta HTTP non deve restare appesa
    ad aspettarle. Lo stesso script e' lanciabile anche da terminale.
    """
    _check_csrf(user, csrf_token)
    if _aggiunta_foto_in_corso():
        log_event("INFO", "admin", "Aggiunta foto: gia' in corso, richiesta ignorata")
        return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
    subprocess.Popen(
        [_SCRIPT_AGGIUNTA_FOTO],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    log_event("INFO", "admin", "Aggiunta foto avviata dal pannello")
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
                       csrf_token: str = Form(...),
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
def ricerche_svuota(request: Request, csrf_token: str = Form(...),
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


# ---------------- Stato del sistema ----------------

# Lo stesso file che il timer photocarcifo-monitor.py scrive ogni 5 minuti
# (vedi script/photocarcifo-monitor.py, scrivi_stato()): questa pagina lo
# LEGGE soltanto, non rifà nessun controllo — nessun integrity_check,
# nessuna scansione NAS, nessun restore ad ogni apertura. Il file è
# leggibile dal gruppo "photocarcifo" (permesso 640) apposta per questa
# pagina: non contiene segreti, solo booleani/percentuali/timestamp.
_STATO_MONITOR = "/var/lib/photocarcifo/monitor-stato.json"

# Il mount in scrittura (backup/export sul NAS) non ha un proprio campo in
# config.py: lo usano solo script fuori dal processo web (photocarcifo-
# db-backup.sh, deploy/photocarcifo-export-config.sh, il monitor). Stessa
# costante duplicata li', non c'è un meccanismo di configurazione
# condiviso fra gli script di sistema e l'applicazione FastAPI.
_NAS_SCRITTURA = "/mnt/magazzino-rw"

# I soli servizi/timer di cui ha senso mostrare lo stato qui: l'app stessa,
# i due che il monitor già sorveglia (bot, nginx), e i quattro timer dietro
# a scanner/monitor/backup/export — esattamente quello che questa pagina
# racconta. Non fail2ban, non il pannello: fuori tema.
_SERVIZI_MOSTRATI = [
    ("photocarcifo.service", "Applicazione"),
    ("photocarcifo-bot.service", "Bot Telegram"),
    ("nginx.service", "Nginx"),
    ("photocarcifo-scan.timer", "Scanner (timer)"),
    ("photocarcifo-monitor.timer", "Monitor (timer)"),
    ("photocarcifo-db-backup.timer", "Backup DB (timer)"),
    ("photocarcifo-export-config.timer", "Export config (timer)"),
]


def _leggi_stato_monitor() -> dict:
    """Non deve mai far fallire la pagina: se il file manca, è illeggibile
    o è un JSON rotto a metà scrittura (raro: scrivi_stato() sposta con
    os.replace, ma un lettore nel millisecondo sbagliato può ancora
    incontrare il file appena creato), si torna un dizionario vuoto e la
    pagina mostra "sconosciuto" ovunque invece di un errore 500."""
    try:
        with open(_STATO_MONITOR, encoding="utf-8") as f:
            dati = json.load(f)
    except (OSError, ValueError):
        return {}
    # json.load riesce anche su un file che contiene solo "null" o una
    # lista: sintatticamente valido ma non e' il dizionario che ci si
    # aspetta. Meglio un dizionario vuoto (-> "sconosciuto" in pagina) che
    # un AttributeError piu' avanti su stato.get(...).
    return dati if isinstance(dati, dict) else {}


def _stato_servizio(nome: str) -> str:
    """systemctl is-active, sola lettura: nessun privilegio nuovo, è la
    stessa identica chiamata che il monitor fa già da solo ogni 5 minuti
    (controlla_servizio in photocarcifo-monitor.py) — verificato che
    l'utente con cui gira l'app (photocarcifo, non root) può eseguirla
    senza bisogno di sudo. Timeout breve: se systemd/dbus fosse lento, la
    pagina non deve restare ferma ad aspettarlo."""
    try:
        r = subprocess.run(["systemctl", "is-active", nome],
                           capture_output=True, text=True, timeout=3)
        return r.stdout.strip() or "sconosciuto"
    except Exception:
        return "sconosciuto"


def _pillola(ok) -> tuple[str, str]:
    """True/False/None -> (etichetta, classe CSS). Le classi sono le
    stesse nas-ok/nas-err già in uso nel resto del pannello (vedi
    dashboard.html), qui estese a quattro stati invece di due — nessun
    sistema di colori nuovo, solo due varianti in più dello stesso."""
    if ok is True:
        return "OK", "nas-ok"
    if ok is False:
        return "ERRORE", "nas-err"
    return "SCONOSCIUTO", "nas-unknown"


def _pillola_servizio(stato_testo: str) -> tuple[str, str]:
    if stato_testo == "active":
        return "ATTIVO", "nas-ok"
    if stato_testo in ("inactive", "dead"):
        return "INATTIVO", "nas-warn"
    if stato_testo == "failed":
        return "FALLITO", "nas-err"
    return "SCONOSCIUTO", "nas-unknown"


def _pillola_export(ok) -> tuple[str, str]:
    """Come _pillola, ma per l'export configurazione: None qui non vuol
    dire "non ancora controllato", vuol dire specificamente "NAS-scrittura
    giu', impossibile dire se l'export sia aggiornato" (vedi
    controlla_export_config nel monitor) — l'etichetta lo dice esplicito
    invece del generico SCONOSCIUTO usato altrove."""
    if ok is True:
        return "OK", "nas-ok"
    if ok is False:
        return "ERRORE", "nas-err"
    return "NON VERIFICABILE", "nas-unknown"


def _pillola_disco(livello: str) -> tuple[str, str]:
    if livello == "ok":
        return "OK", "nas-ok"
    if livello == "warning":
        return "ATTENZIONE", "nas-warn"
    if livello == "critical":
        return "CRITICO", "nas-err"
    return "SCONOSCIUTO", "nas-unknown"


def _fa(quando_iso, adesso=None) -> str:
    """'Xm fa'/'Xh fa'/'Xg fa' a partire da un timestamp ISO — lo stesso
    tipo di calcolo che il bot fa per /health (_eta_check), qui solo per
    la scritta, non per decidere uno stato."""
    if not quando_iso:
        return "mai"
    try:
        quando = datetime.fromisoformat(quando_iso)
    except (ValueError, TypeError):
        return "data sconosciuta"
    ora = adesso or (datetime.now(quando.tzinfo) if quando.tzinfo else datetime.now())
    minuti = (ora - quando).total_seconds() / 60
    if minuti < 0:
        return "adesso"
    if minuti < 60:
        return f"{minuti:.0f}m fa"
    if minuti < 60 * 24:
        return f"{minuti / 60:.0f}h fa"
    return f"{minuti / 60 / 24:.0f}g fa"


@router.get("/stato-sistema", response_class=HTMLResponse)
def stato_sistema(request: Request, user: dict = Depends(require_admin_user)):
    stato = _leggi_stato_monitor()
    d = stato.get("dettagli_ultimo", {})
    ultimo_check = stato.get("ultimo_check")

    # L'ultima scansione: stessa tabella che /admin/logs già mostra,
    # filtrata alla sola categoria "scan" e limitata a una riga — non una
    # query nuova e pesante, la stessa identica fonte con un WHERE in più.
    with get_db() as conn:
        ultima_scan = conn.execute(
            "SELECT ts, level, message FROM logs WHERE category='scan' "
            "ORDER BY id DESC LIMIT 1").fetchone()
    scan_ok, scan_dettaglio, scan_quando = None, "nessuna scansione registrata", None
    if ultima_scan:
        scan_ok = ultima_scan["level"] == "INFO"
        scan_dettaglio = ultima_scan["message"][:140]
        scan_quando = ultima_scan["ts"]

    # Byte reali dello stesso filesystem che il monitor già misura
    # (/opt/photocarcifo/data — un semplice statvfs, non costoso), ma lo
    # stato (ok/attenzione/critico) è quello che il monitor ha già deciso
    # con le sue soglie: niente doppie soglie da tenere allineate a mano.
    disco = {"total": 0, "used": 0, "free": 0}
    try:
        u = shutil.disk_usage("/opt/photocarcifo")
        disco = {"total": u.total, "used": u.used, "free": u.free}
    except OSError:
        pass
    disco["pct_usato"] = round(100 - d.get("disco_liberi_pct", 0), 1) \
        if d.get("disco_liberi_pct") is not None else None

    servizi = []
    for unita, etichetta in _SERVIZI_MOSTRATI:
        stato_testo = _stato_servizio(unita)
        etichetta_stato, classe = _pillola_servizio(stato_testo)
        servizi.append({"nome": etichetta, "unita": unita,
                        "stato_testo": stato_testo,
                        "etichetta_stato": etichetta_stato, "classe": classe})

    def card(ok, **extra):
        etichetta_stato, classe = _pillola(ok)
        return {"etichetta_stato": etichetta_stato, "classe": classe, **extra}

    etichetta_disco, classe_disco = _pillola_disco(d.get("disco_livello"))
    disco["etichetta_stato"], disco["classe"] = etichetta_disco, classe_disco

    etichetta_export, classe_export = _pillola_export(d.get("export_config_ok"))
    export_config = {"etichetta_stato": etichetta_export, "classe": classe_export,
                     "dettaglio": d.get("export_config_dettaglio") or "—"}

    contesto = {
        "user": user,
        "ultimo_check": ultimo_check, "ultimo_check_fa": _fa(ultimo_check),

        "nas_lettura": card(d.get("nas_ok"), percorso=str(get_settings().photo_root_path)),
        "nas_scrittura": card(d.get("nas_backup_ok"), percorso=_NAS_SCRITTURA),

        "scan": card(scan_ok, dettaglio=scan_dettaglio,
                    quando=scan_quando, quando_fa=_fa(scan_quando)),

        "monitor": card(ultimo_check is not None,
                        quando=ultimo_check, quando_fa=_fa(ultimo_check)),

        "backup": card(d.get("backup_db_ok"), dettaglio=d.get("backup_db_dettaglio") or "—"),

        "restore_check": card(d.get("backup_db_integrity_ok"),
                              quando=d.get("backup_db_integrity_quando"),
                              quando_fa=_fa(d.get("backup_db_integrity_quando"))),

        "export_config": export_config,

        "disco_ct": disco,

        "servizi": servizi,
    }
    return templates.TemplateResponse(request, "admin/stato_sistema.html", contesto)


# ---------------- Richieste di contatto ----------------

# Stati ammessi, stesso elenco documentato in database.py e in contattami.py.
_STATI_RICHIESTA = ("Nuova", "Letta", "In lavorazione", "Chiusa", "Archiviata")


_ORDINI_RICHIESTA = {"recenti": "DESC", "vecchi": "ASC"}


@router.get("/richieste", response_class=HTMLResponse)
def richieste_page(request: Request, user: dict = Depends(require_admin_user),
                   stato: str = "", q: str = "", ordine: str = "recenti"):
    """Elenco delle richieste arrivate dal modulo pubblico /contattami,
    con filtro per stato, ricerca semplice e ordinamento per data.

    Whitelist esplicita per stato e ordine: nessuno dei due entra mai nella
    query se non e' uno dei valori ammessi, cosi' l'input dell'utente non
    puo' toccare il testo SQL."""
    stato = stato if stato in _STATI_RICHIESTA else ""
    verso = _ORDINI_RICHIESTA.get(ordine, _ORDINI_RICHIESTA["recenti"])
    ordine = ordine if ordine in _ORDINI_RICHIESTA else "recenti"
    q = q.strip()

    condizioni = []
    parametri = []
    if stato:
        condizioni.append("stato=?")
        parametri.append(stato)
    if q:
        condizioni.append(
            "(nome LIKE ? ESCAPE '\\' OR cognome LIKE ? ESCAPE '\\' OR "
            "email LIKE ? ESCAPE '\\' OR motivo LIKE ? ESCAPE '\\')")
        simile = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        parametri.extend([simile, simile, simile, simile])
    dove = (" WHERE " + " AND ".join(condizioni)) if condizioni else ""

    with get_db() as conn:
        righe = conn.execute(
            "SELECT id, nome, cognome, motivo, creato_at, stato "
            "FROM richieste_contatto" + dove +
            f" ORDER BY creato_at {verso}", parametri).fetchall()
        # Conteggi per stato, per i chip dei filtri: sempre sul totale
        # (senza il filtro di stato) cosi' i numeri restano stabili mentre
        # si passa da un chip all'altro; la ricerca testuale invece li
        # restringe, e' comoda per capire "quante Nuove restano" quando si
        # sta cercando qualcosa di preciso.
        dove_conteggi = (" WHERE " + " AND ".join(condizioni[1:] if stato else condizioni)) \
            if (condizioni[1:] if stato else condizioni) else ""
        parametri_conteggi = parametri[1:] if stato else parametri
        conteggi_righe = conn.execute(
            "SELECT stato, COUNT(*) c FROM richieste_contatto" + dove_conteggi +
            " GROUP BY stato", parametri_conteggi).fetchall()
    conteggi = {r["stato"]: r["c"] for r in conteggi_righe}
    return templates.TemplateResponse(request, "admin/richieste.html", {
        "user": user, "richieste": [dict(r) for r in righe],
        "stati": _STATI_RICHIESTA, "conteggi": conteggi,
        "filtro_stato": stato, "filtro_q": q, "filtro_ordine": ordine,
        "totale": sum(conteggi.values())})


@router.get("/richieste/{richiesta_id}", response_class=HTMLResponse)
def richiesta_dettaglio(request: Request, richiesta_id: int,
                        user: dict = Depends(require_admin_user)):
    with get_db() as conn:
        riga = conn.execute(
            "SELECT * FROM richieste_contatto WHERE id=?", (richiesta_id,)).fetchone()
    if not riga:
        raise HTTPException(status_code=404, detail="Richiesta non trovata")
    return templates.TemplateResponse(request, "admin/richiesta_dettaglio.html", {
        "user": user, "r": dict(riga), "stati": _STATI_RICHIESTA})


@router.post("/richieste/{richiesta_id}/stato")
def richiesta_cambia_stato(request: Request, richiesta_id: int,
                           csrf_token: str = Form(...), stato: str = Form(...),
                           user: dict = Depends(require_admin_api)):
    _check_csrf(user, csrf_token)
    if stato not in _STATI_RICHIESTA:
        raise HTTPException(status_code=400, detail="Stato non valido")
    with get_db() as conn:
        riga = conn.execute(
            "SELECT id FROM richieste_contatto WHERE id=?", (richiesta_id,)).fetchone()
        if not riga:
            raise HTTPException(status_code=404, detail="Richiesta non trovata")
        conn.execute("UPDATE richieste_contatto SET stato=? WHERE id=?",
                     (stato, richiesta_id))
    return RedirectResponse(url=f"/admin/richieste/{richiesta_id}",
                            status_code=status.HTTP_303_SEE_OTHER)


@router.post("/richieste/{richiesta_id}/elimina")
def richiesta_elimina(request: Request, richiesta_id: int,
                      csrf_token: str = Form(...),
                      user: dict = Depends(require_admin_api)):
    _check_csrf(user, csrf_token)
    with get_db() as conn:
        riga = conn.execute(
            "SELECT id FROM richieste_contatto WHERE id=?", (richiesta_id,)).fetchone()
        if not riga:
            raise HTTPException(status_code=404, detail="Richiesta non trovata")
        conn.execute("DELETE FROM richieste_contatto WHERE id=?", (richiesta_id,))
    return RedirectResponse(url="/admin/richieste", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/condivisioni", response_class=HTMLResponse)
def condivisioni_page(request: Request, user: dict = Depends(require_admin_user)):
    """Elenco dei link di condivisione attivi: singola fotografia
    (media.share_token) e selezione multipla (tabella condivisioni)."""
    settings = get_settings()
    base = settings.site_url.rstrip("/")
    from .tree import scaduto, giorni_rimasti
    with get_db() as conn:
        singole = conn.execute(
            "SELECT m.id, m.filename, m.share_token, m.share_created_at, "
            "m.share_expires_at, n.title AS album "
            "FROM media m JOIN nodes n ON n.id = m.node_id "
            "WHERE m.share_token IS NOT NULL "
            "ORDER BY m.share_created_at DESC").fetchall()
        selezioni = conn.execute(
            "SELECT id, token, media_ids, created_at, expires_at FROM condivisioni "
            "ORDER BY created_at DESC").fetchall()
    singole_out = [{"id": r["id"], "filename": r["filename"], "album": r["album"],
                    "created_at": r["share_created_at"],
                    "expires_at": r["share_expires_at"], "scaduto": scaduto(r["share_expires_at"]),
                    "giorni_rimasti": giorni_rimasti(r["share_expires_at"]),
                    "url": f"{base}/f/{r['share_token']}"} for r in singole]
    selezioni_out = [{"id": r["id"],
                      "conta": len(r["media_ids"].split(",")) if r["media_ids"] else 0,
                      "created_at": r["created_at"],
                      "expires_at": r["expires_at"], "scaduto": scaduto(r["expires_at"]),
                      "giorni_rimasti": giorni_rimasti(r["expires_at"]),
                      "url": f"{base}/fs/{r['token']}"} for r in selezioni]
    return templates.TemplateResponse(request, "admin/condivisioni.html", {
        "user": user, "singole": singole_out, "selezioni": selezioni_out})
