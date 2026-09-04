"""Scanner del filesystem Synology -> indice ad ALBERO."""
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from .config import get_settings
from .database import get_db, log_event, ricalcola_date_album
from .indexnow import notify_indexnow
from .numeri import azzera_ocr

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v"}
IGNORE_DIRS = {"@eadir", "pwg_representative", "#recycle", "_cestino", "_backup_sito", "@tmp", "@sharesnap"}
PRIVATE_TOP = "SHOOTING_PRIVATI"


class NASNonDisponibile(Exception):
    """Il NAS e' caduto a meta' di una scansione gia' iniziata.

    Distingue "questo file/cartella e' stato davvero rimosso sul NAS"
    da "il NAS ha smesso di rispondere mentre lo stavamo leggendo": la
    prima e' un'informazione vera che va registrata, la seconda non lo
    e' e non deve mai tradursi in cancellazioni. Interrompe subito
    run(), prima che il giro prosegua sulle categorie/cartelle non
    ancora visitate scambiando per vuoto cio' che non e' raggiungibile."""


def _slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[\s_-]+", "-", text)
    return text.strip("-") or "n"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(msg: str) -> None:
    print(f"[scan] {msg}", flush=True)


def _prettify(name: str) -> str:
    return name.replace("_", " ").strip()


def _is_ignored(name: str) -> bool:
    return name.lower() in IGNORE_DIRS


def _nas_disponibile(root: Path) -> bool:
    """Vero solo se il NAS e' realmente montato e leggibile, non solo se
    la cartella esiste.

    root.exists() da solo non basta: se l'NFS si stacca, il mountpoint
    locale resta li' come una normale directory (spesso vuota) e
    "esiste" comunque agli occhi del filesystem. Uno scan che si fidasse
    solo di .exists() vedrebbe un NAS staccato come "cartella svuotata"
    e cancellerebbe dal database ogni nodo e ogni fotografia che pensava
    di trovarci: un NAS offline non deve mai poter sembrare un NAS
    vuoto. os.path.ismount() guarda invece il dispositivo/mount reale
    (st_dev), non il solo contenuto — e' la stessa distinzione che
    "mount" o "findmnt" fanno da riga di comando."""
    try:
        if not os.path.ismount(root):
            return False
        # Il mount puo' risultare tecnicamente attivo ma non piu'
        # rispondere (NFS "soft" che ha appena iniziato a fallire le
        # richieste): un tentativo di lettura reale lo smaschera.
        with os.scandir(root):
            pass
        return True
    except OSError:
        return False


def _media_kind(suffix: str):
    s = suffix.lower()
    if s in IMAGE_EXTS:
        return "image"
    if s in VIDEO_EXTS:
        return "video"
    return None


def _image_dimensions(path: Path):
    try:
        with Image.open(path) as im:
            return im.width, im.height
    except Exception:
        return 0, 0


def _video_meta(path: Path):
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height:format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        lines = [l for l in out.stdout.strip().splitlines() if l]
        w = int(lines[0]) if len(lines) > 0 else 0
        h = int(lines[1]) if len(lines) > 1 else 0
        d = float(lines[2]) if len(lines) > 2 else 0.0
        return w, h, d
    except Exception:
        return 0, 0, 0.0


class Scanner:
    def __init__(self, full: bool = False):
        self.settings = get_settings()
        self.root = self.settings.photo_root_path
        self.full = full
        self.result = {"nodes_added": 0, "nodes_removed": 0,
                       "media_added": 0, "media_updated": 0, "media_removed": 0}
        # Slug degli album pubblici toccati da questa scansione (creati,
        # tornati pubblici, o svuotati/spariti): notificati a IndexNow in
        # un solo invio a fine run(), non uno alla volta durante il giro
        # dell'albero. Vedi _walk() e run().
        self._slug_da_notificare = set()

    def _unique_slug(self, conn, base: str, rel_path: str) -> str:
        row = conn.execute("SELECT slug FROM nodes WHERE rel_path=?", (rel_path,)).fetchone()
        if row:
            return row["slug"]
        # Prima si controllava uno slug alla volta con una query per
        # tentativo (slug, slug-2, slug-3, ...): su una cartella con molti
        # doppioni erano altrettante query sequenziali. Si leggono invece
        # tutti gli slug che iniziano con la base in una sola query e si
        # calcola in Python il primo libero.
        fuga = base.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        esistenti = {r["slug"] for r in conn.execute(
            "SELECT slug FROM nodes WHERE slug LIKE ? ESCAPE '\\'",
            (fuga + "%",)).fetchall()}
        if base not in esistenti:
            return base
        i = 2
        while f"{base}-{i}" in esistenti:
            i += 1
        return f"{base}-{i}"

    def _get_or_create_node(self, conn, abs_dir: Path, parent_id, depth: int,
                            is_private: int) -> int:
        rel = str(abs_dir.relative_to(self.root))
        rel = "" if rel == "." else rel
        name = abs_dir.name
        existing = conn.execute("SELECT id FROM nodes WHERE rel_path=?", (rel,)).fetchone()
        if existing:
            return existing["id"]
        slug = self._unique_slug(conn, _slugify(name), rel)
        token = None
        if is_private:
            import secrets
            token = secrets.token_urlsafe(16)
        # Una cartella nuova dentro un album nascosto nasce nascosta.
        #
        # Il 22/08/2026, dividendo tre album in FOTO/ e VIDEO/, le due
        # cartelle nuove dentro un album nascosto sono nate visibili: 48
        # fotografie che erano state tolte dal sito di proposito sono
        # tornate raggiungibili da chiunque. La protezione riservata
        # (is_private) veniva gia' passata da chi chiama; questa no, e
        # nessuno se ne sarebbe accorto finche' qualcuno non ci fosse
        # arrivato. Basta aggiungere una sottocartella sul NAS.
        nascosto = 0
        if parent_id:
            riga = conn.execute("SELECT hidden FROM nodes WHERE id=?",
                                (parent_id,)).fetchone()
            nascosto = int(riga["hidden"]) if riga else 0
        cur = conn.execute(
            "INSERT INTO nodes(parent_id, slug, rel_path, name, title, depth, "
            "is_private, access_token, hidden, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (parent_id, slug, rel, name, _prettify(name), depth,
             is_private, token, nascosto, _now(), _now()),
        )
        self.result["nodes_added"] += 1
        # La notifica IndexNow vera e propria parte da _walk(), non da qui:
        # appena creato il nodo non ha ancora total_media (lo calcola
        # _walk() dopo aver letto le foto e le sottocartelle), quindi non si
        # sa ancora se sara' un album pubblico con contenuto o una cartella
        # vuota che verra' tolta subito dopo.
        return cur.lastrowid

    def _sync_media(self, conn, node_id: int, abs_dir: Path):
        fs_media = {}
        try:
            with os.scandir(abs_dir) as it:
                for entry in it:
                    try:
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        kind = _media_kind(Path(entry.name).suffix)
                        if not kind:
                            continue
                        rel = str(Path(entry.path).relative_to(self.root))
                        fs_media[rel] = (entry.stat(), kind)
                    except OSError:
                        continue
        except OSError:
            # Cartella illeggibile: se il NAS e' ancora raggiungibile e'
            # un problema locale a questa sola cartella (permessi,
            # simlink rotto) e si prosegue come prima trattandola vuota;
            # se invece il NAS e' sparito, non e' vuota, e' irraggiungibile
            # — tutta la scansione va fermata, non solo questa cartella.
            if not _nas_disponibile(self.root):
                raise NASNonDisponibile(str(abs_dir))
            return 0

        db_media = {r["rel_path"]: r for r in conn.execute(
            "SELECT id, rel_path, mtime, size_bytes FROM media WHERE node_id=?",
            (node_id,)).fetchall()}

        for rel_path, row in db_media.items():
            if rel_path not in fs_media:
                conn.execute("DELETE FROM media WHERE id=?", (row["id"],))
                self.result["media_removed"] += 1

        for rel_path, (st, kind) in fs_media.items():
            existing = db_media.get(rel_path)
            changed = (existing is None
                       or abs(existing["mtime"] - st.st_mtime) > 1e-6
                       or existing["size_bytes"] != st.st_size
                       or self.full)
            if not changed:
                continue
            filename = Path(rel_path).name
            w = h = 0
            dur = 0.0
            if kind == "image":
                w, h = _image_dimensions(self.root / rel_path)
            else:
                w, h, dur = _video_meta(self.root / rel_path)
            if existing:
                conn.execute(
                    "UPDATE media SET kind=?, mtime=?, size_bytes=?, width=?, "
                    "height=?, duration=? WHERE id=?",
                    (kind, st.st_mtime, st.st_size, w, h, dur, existing["id"]))
                # La foto e' cambiata sul NAS: i numeri letti prima non
                # valgono piu' e va rianalizzata. Quelli scritti a mano
                # restano.
                azzera_ocr(conn, existing["id"])
                self.result["media_updated"] += 1
            else:
                conn.execute(
                    "INSERT INTO media(node_id, kind, rel_path, filename, width, "
                    "height, duration, size_bytes, mtime, created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (node_id, kind, rel_path, filename, w, h, dur,
                     st.st_size, st.st_mtime, _now()))
                self.result["media_added"] += 1

        return len(fs_media)

    def _configurato(self, conn, node_id: int) -> bool:
        """Vero se questa cartella e' stata impostata a mano dal pannello.

        Le cartelle senza fotografie vengono tolte dall'indice per non
        lasciare voci vuote. Se pero' una cartella risulta vuota solo per un
        errore momentaneo di lettura del NAS, cancellarla farebbe perdere il
        link di condivisione, la password e il titolo: alla scansione
        successiva verrebbe ricreata con un link NUOVO e tutti i
        collegamenti gia' consegnati ai clienti smetterebbero di funzionare.
        Le cartelle sparite davvero vengono comunque rimosse da run(), che
        controlla se esistono ancora sul disco.
        """
        r = conn.execute(
            "SELECT access_token, password_hash, cover_media_id, hidden, "
            "       is_private, description "
            "FROM nodes WHERE id=?", (node_id,)).fetchone()
        if not r:
            return False
        return bool(r["access_token"] or r["password_hash"] or r["cover_media_id"]
                    or r["hidden"] or r["is_private"] or (r["description"] or "").strip())

    def _walk(self, conn, abs_dir: Path, parent_id, depth: int, inherited_private: int) -> int:
        name = abs_dir.name
        is_private = inherited_private or (1 if name == PRIVATE_TOP else 0)

        subdirs = []
        try:
            with os.scandir(abs_dir) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False) and not _is_ignored(entry.name):
                            subdirs.append(Path(entry.path))
                    except OSError:
                        continue
        except OSError:
            if not _nas_disponibile(self.root):
                raise NASNonDisponibile(str(abs_dir))
            return 0

        node_id = self._get_or_create_node(conn, abs_dir, parent_id, depth, is_private)

        # Stato pubblico PRIMA di questo giro: serve solo per capire, dopo
        # l'update piu' sotto, se questa scansione fa comparire o sparire
        # l'album dai risultati di ricerca (foto arrivate/svuotate sul NAS,
        # non un cambio di privacy dal pannello: quello lo notifica gia'
        # admin_nodes.py per conto suo). slug=None per un nodo appena creato,
        # che quindi non puo' essere stato pubblico prima di ora.
        riga = conn.execute("SELECT slug, total_media, hidden FROM nodes WHERE id=?",
                            (node_id,)).fetchone()
        slug = riga["slug"]
        era_pubblico = bool(riga["total_media"] and not is_private and not riga["hidden"])

        direct = self._sync_media(conn, node_id, abs_dir)

        subtotal = direct
        for sub in sorted(subdirs):
            subtotal += self._walk(conn, sub, node_id, depth + 1, is_private)

        conn.execute("UPDATE nodes SET direct_media=?, total_media=? WHERE id=?",
                     (direct, subtotal, node_id))

        ora_pubblico = bool(subtotal and not is_private and not riga["hidden"])
        if era_pubblico != ora_pubblico:
            # Comparso o sparito dai risultati pubblici in questa
            # scansione: vale la pena farlo ricontrollare da IndexNow in
            # entrambi i casi, che lo trovi se e' comparso o che tolga dai
            # risultati una pagina ormai vuota/404 se e' sparito.
            self._slug_da_notificare.add(slug)

        if subtotal == 0 and not self._configurato(conn, node_id):
            conn.execute("DELETE FROM nodes WHERE id=?", (node_id,))
            # Il nodo puo' essere stato creato proprio in questo giro (una
            # riga piu' su, in _get_or_create_node) e poi scartato subito
            # perche' vuota: e' comunque una cancellazione avvenuta durante
            # questo scan, va contata come le altre (vedi riga ~373) o il log
            # mostra solo la meta' dell'evento ("+3 aggiunti" senza mai un
            # "-3 rimossi" a bilanciarlo, anche se il DB resta invariato).
            self.result["nodes_removed"] += 1
        else:
            conn.commit()
            _log(f"{'  '*depth}{_prettify(name)}: {direct} diretti, {subtotal} totali")

        return subtotal

    def run(self) -> dict:
        if not _nas_disponibile(self.root):
            # Qui ci si ferma PRIMA di toccare qualunque riga di nodes o
            # media: il resto di run() cancella dal database cio' che
            # non trova piu' sul NAS, quindi se il NAS non e' davvero
            # raggiungibile bisogna uscire subito, non entrare nel giro
            # e interpretare l'assenza come "e' stato tutto rimosso".
            log_event("ERROR", "scan", f"NAS non disponibile — scan annullato: {self.root}")
            _log(f"NAS non disponibile — scan annullato: {self.root}")
            return self.result

        _log("Avvio scansione ad albero...")
        with get_db() as conn:
            try:
                righe = conn.execute(
                    "SELECT id, rel_path, slug, total_media, is_private, hidden "
                    "FROM nodes").fetchall()
                for i, r in enumerate(righe):
                    try:
                        assente = not (self.root / r["rel_path"]).exists()
                    except OSError:
                        assente = True
                    if not assente:
                        continue
                    # Prima di cancellare, non ci si fida del primo
                    # .exists() negativo da solo: puo' essere il NAS
                    # caduto proprio durante questo giro (che scorre
                    # TUTTI i nodi del database, anche migliaia) invece
                    # di una cartella davvero rimossa. Stesso principio
                    # gia' applicato in _walk()/_sync_media(): qui serve
                    # perche' e' l'altro punto del file che cancella
                    # nodes in base alla sola presenza sul filesystem.
                    if not _nas_disponibile(self.root):
                        raise NASNonDisponibile(
                            f"durante la pulizia nodi (riga {i+1}/{len(righe)}): {r['rel_path']}")
                    conn.execute("DELETE FROM nodes WHERE id=?", (r["id"],))
                    self.result["nodes_removed"] += 1
                    if r["total_media"] and not r["is_private"] and not r["hidden"]:
                        # Cartella intera sparita dal NAS: era un album
                        # pubblico indicizzabile, quindi la sua pagina va
                        # segnalata come cambiata anche qui, non solo nel
                        # caso "svuotata ma ancora presente" gestito in
                        # _walk().
                        self._slug_da_notificare.add(r["slug"])
                conn.commit()

                top = []
                try:
                    with os.scandir(self.root) as it:
                        for entry in it:
                            if entry.is_dir(follow_symlinks=False) and not _is_ignored(entry.name):
                                top.append(Path(entry.path))
                except OSError:
                    if not _nas_disponibile(self.root):
                        raise NASNonDisponibile(f"listato categorie: {self.root}")
                for cat in sorted(top):
                    self._walk(conn, cat, None, 0, 0)
            except NASNonDisponibile as exc:
                log_event("ERROR", "scan",
                          f"NAS caduto durante lo scan, interrotto a meta': {exc}")
                _log(f"NAS caduto durante lo scan, interrotto a meta': {exc}")
                # Niente IndexNow: la lista di slug raccolta finora
                # riflette solo la parte di albero vista prima della
                # caduta, non lo stato reale del sito. I DELETE gia'
                # committati sopra (se il crollo e' avvenuto dopo quel
                # commit) non si possono disfare qui: e' per questo che
                # ogni cancellazione, prima di eseguire, riverifica
                # _nas_disponibile() invece di limitarsi a un controllo
                # una tantum a inizio funzione.
                self._slug_da_notificare.clear()
                return self.result
            # Le pagine ordinano per data dello scatto piu' recente: la si
            # calcola qui una volta sola, non a ogni visita.
            ricalcola_date_album(conn)

        log_event("INFO", "scan", f"Scan ad albero completata: {self.result}")
        _log(f"COMPLETATA: {self.result}")

        if self._slug_da_notificare:
            # Un solo invio in batch a fine scansione, non uno per album:
            # una scansione che fa comparire/sparire venti album manda una
            # sola chiamata a IndexNow con venti indirizzi, non venti
            # chiamate. Lo scanner gira come processo a se' (systemd timer,
            # non dentro una richiesta web), quindi qui l'attesa di rete
            # non rallenta nessun visitatore.
            base = self.settings.site_url.rstrip("/")
            urls = [f"{base}/n/{s}" for s in self._slug_da_notificare]
            notify_indexnow(urls)

        return self.result


def scan(full: bool = False) -> dict:
    return Scanner(full=full).run()
