"""Numeri di gara (tabelle) associati alle fotografie.

Ogni foto puo' essere collegata a uno o piu' numeri di gara: quelli letti
sulla tabella degli atleti. Grazie a questo indice un pilota che scrive il
proprio numero nella barra di ricerca ritrova tutti i suoi scatti.

I numeri arrivano da due strade:

- ``ocr``      riconoscimento automatico (vedi :mod:`app.ocr`);
- ``manuale``  inseriti o corretti a mano dal pannello.

Quelli manuali hanno sempre la precedenza: una nuova passata di
riconoscimento non li tocca mai. Qui stanno solo la normalizzazione e il
salvataggio, la lettura delle immagini e' in :mod:`app.ocr`.
"""
import re
from datetime import datetime, timezone

ORIGINE_OCR = "ocr"
ORIGINE_MANUALE = "manuale"

# Query che valgono come ricerca per numero: cifre eventualmente precedute
# da simboli comuni ("#198", "n. 198", "n°198").
_RE_QUERY = re.compile(r"^[#n°.\s]*(\d{1,4})\s*$", re.IGNORECASE)

# Separatori accettati quando si scrivono piu' numeri a mano
_RE_SEPARATORI = re.compile(r"[^0-9]+")


def normalizza(grezzo) -> str | None:
    """Riduce un numero alla sua forma canonica, None se non e' un numero.

    Gli zeri iniziali spariscono, cosi' "007", "07" e "7" finiscono sullo
    stesso valore e chi cerca in un modo trova anche gli altri.
    """
    cifre = "".join(c for c in str(grezzo) if c.isdigit())
    if not cifre:
        return None
    return cifre.lstrip("0") or "0"


def leggi_query(query: str) -> str | None:
    """Interpreta la stringa di ricerca come numero di gara.

    Restituisce il numero normalizzato, oppure None se e' testo libero: in
    quel caso la ricerca resta quella classica per cartelle.
    """
    trovato = _RE_QUERY.match((query or "").strip())
    return normalizza(trovato.group(1)) if trovato else None


def leggi_elenco(grezzo: str, max_cifre: int = 4) -> list[str]:
    """Interpreta un elenco scritto a mano ("198, 21 7") come lista di numeri."""
    risultato: list[str] = []
    for pezzo in _RE_SEPARATORI.split(grezzo or ""):
        if not pezzo or len(pezzo.lstrip("0") or "0") > max_cifre:
            continue
        valore = normalizza(pezzo)
        if valore and valore not in risultato:
            risultato.append(valore)
    return risultato


def _adesso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------- Lettura ----------------
def numeri_di(conn, media_ids: list[int]) -> dict[int, list[str]]:
    """Mappa {media_id: [numeri]} per un elenco di foto, con una sola query."""
    if not media_ids:
        return {}
    segnaposto = ",".join("?" * len(media_ids))
    righe = conn.execute(
        f"SELECT media_id, numero FROM media_numeri "
        f"WHERE media_id IN ({segnaposto}) ORDER BY CAST(numero AS INTEGER)",
        media_ids).fetchall()
    fuori: dict[int, list[str]] = {}
    for r in righe:
        fuori.setdefault(r["media_id"], []).append(r["numero"])
    return fuori


def cartelle_visibili(conn, sbloccati: list | None = None,
                      admin: bool = False) -> list[int]:
    """Cartelle che questo visitatore ha diritto di vedere nella ricerca.

    Valgono le stesse regole della ricerca per cartelle: quelle nascoste non
    escono mai, quelle riservate solo a chi possiede il link, e i link
    scaduti non aprono piu' nulla. La scadenza si controlla qui e non in SQL
    perche' e' una data ISO, non confrontabile in modo affidabile; le
    cartelle sono poche, quindi costa nulla.
    """
    from .routers.tree import scaduto
    propri = {int(v) for v in (sbloccati or [])}
    fuori = []
    for r in conn.execute(
            "SELECT id, is_private, hidden, expires_at FROM nodes").fetchall():
        if admin:
            fuori.append(r["id"])
            continue
        if r["hidden"]:
            continue
        if r["is_private"] and r["id"] not in propri:
            continue
        if scaduto(r["expires_at"]):
            continue
        fuori.append(r["id"])
    return fuori


def conta_foto(conn, numero: str, consentite: list[int]) -> int:
    """Quante fotografie hanno questo numero, fra quelle visibili."""
    if not consentite:
        return 0
    segnaposto = ",".join("?" * len(consentite))
    return conn.execute(
        f"SELECT COUNT(*) c FROM media_numeri x JOIN media m ON m.id = x.media_id "
        f"WHERE x.numero = ? AND m.node_id IN ({segnaposto})",
        [numero, *consentite]).fetchone()["c"]


def cerca_foto(conn, numero: str, consentite: list[int],
               limite: int = 120, salta: int = 0) -> list[dict]:
    """Una pagina di fotografie collegate a un numero di gara.

    I risultati sono impaginati invece che troncati: un numero molto usato
    puo' comparire in migliaia di scatti e devono restare tutti
    raggiungibili.
    """
    if not consentite:
        return []
    segnaposto = ",".join("?" * len(consentite))
    righe = conn.execute(
        f"SELECT m.id, m.kind, m.filename, m.width, m.height, "
        f"n.id AS node_id, n.slug, n.title, n.rel_path, n.is_private, "
        f"n.access_token, n.downloads_enabled "
        f"FROM media_numeri x "
        f"JOIN media m ON m.id = x.media_id "
        f"JOIN nodes n ON n.id = m.node_id "
        f"WHERE x.numero = ? AND m.node_id IN ({segnaposto}) "
        f"ORDER BY m.mtime DESC, m.sort_order, m.filename LIMIT ? OFFSET ?",
        [numero, *consentite, limite, salta]).fetchall()

    fuori = []
    for r in righe:
        d = dict(r)
        pezzi = r["rel_path"].split("/")
        d["percorso"] = " / ".join(p.replace("_", " ") for p in pezzi)
        fuori.append(d)
    return fuori


def conteggi(conn) -> dict:
    """Contatori per il pannello: stato della coda e numeri indicizzati."""
    def uno(sql: str) -> int:
        return conn.execute(sql).fetchone()["c"]

    return {
        "da_fare": uno("SELECT COUNT(*) c FROM media "
                       "WHERE kind='image' AND ocr_stato IN ('', 'in_corso')"),
        "fatte": uno("SELECT COUNT(*) c FROM media WHERE ocr_stato='fatto'"),
        "illeggibili": uno("SELECT COUNT(*) c FROM media WHERE ocr_stato='errore'"),
        "con_numero": uno("SELECT COUNT(DISTINCT media_id) c FROM media_numeri"),
        "numeri_diversi": uno("SELECT COUNT(DISTINCT numero) c FROM media_numeri"),
    }


# ---------------- Scrittura ----------------
def imposta_manuali(conn, media_id: int, valori: list[str]) -> None:
    """Sostituisce i numeri MANUALI di una foto con quelli indicati.

    Quelli trovati dal riconoscimento restano al loro posto: correggere una
    foto non cancella cio' che e' stato letto sulle altre.
    """
    conn.execute("DELETE FROM media_numeri WHERE media_id=? AND origine=?",
                 (media_id, ORIGINE_MANUALE))
    for valore in valori:
        conn.execute(
            "INSERT INTO media_numeri(media_id, numero, origine, confidenza, created_at) "
            "VALUES(?,?,?,?,?) ON CONFLICT(media_id, numero) DO UPDATE SET "
            "origine=excluded.origine, confidenza=excluded.confidenza",
            (media_id, valore, ORIGINE_MANUALE, 1.0, _adesso()))


def sostituisci_ocr(conn, media_id: int, letture: list[tuple]) -> int:
    """Sostituisce i numeri letti automaticamente per una foto.

    Args:
        letture: quaterne (numero, sicurezza, centro x, centro y, altezza).

    Restituisce quanti numeri sono stati registrati. Se un numero e' gia'
    presente come manuale, la versione corretta a mano vince.
    """
    conn.execute("DELETE FROM media_numeri WHERE media_id=? AND origine=?",
                 (media_id, ORIGINE_OCR))
    scritti = 0
    for lettura in letture:
        valore, confidenza = lettura[0], lettura[1]
        px, py, alt = (lettura[2:5] if len(lettura) >= 5 else (None, None, None))
        cur = conn.execute(
            "INSERT INTO media_numeri(media_id, numero, origine, confidenza, "
            "pos_x, pos_y, altezza, created_at) "
            "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(media_id, numero) DO NOTHING",
            (media_id, valore, ORIGINE_OCR, confidenza, px, py, alt, _adesso()))
        scritti += cur.rowcount or 0
    return scritti


def _mediana(valori: list[float]) -> float:
    ordinati = sorted(valori)
    meta = len(ordinati) // 2
    if len(ordinati) % 2:
        return ordinati[meta]
    return (ordinati[meta - 1] + ordinati[meta]) / 2


def ripulisci_cartelli(conn, raggio: float = 0.05, minimo: int = 5,
                       soglia: float = 0.12) -> list[tuple[str, str, int, int]]:
    """Toglie i numeri che sono cartelli dell'impianto, non tabelle.

    In certi impianti i settori delle tribune sono numerati con cifre grandi
    e nitide: l'OCR le legge con la stessa sicurezza di una tabella e
    nessuna soglia riesce a distinguerle. Si distinguono pero' da come si
    MUOVONO. Il fotografo scatta piu' o meno dallo stesso punto, quindi un
    cartello fisso ricade sempre nello stesso angolo dell'inquadratura,
    foto dopo foto. Un pilota invece attraversa la scena: la sua tabella
    ogni volta e' altrove.

    Quindi, cartella per cartella e numero per numero, si cerca un gruppo di
    letture tutte concentrate nello stesso punto (entro `raggio`, in
    frazione di inquadratura). Se sono almeno `minimo` e coprono piu' di
    `soglia` delle foto con numeri, quel gruppo e' un cartello e si elimina.
    Le letture dello STESSO numero in altre posizioni restano: se un pilota
    ha davvero la tabella 2, le sue foto continuano a uscire.

    Non tocca mai i numeri corretti a mano, e guarda solo le cartelle lette
    per intero: a meta' i conteggi ingannerebbero.

    Returns:
        elenco (titolo cartella, numero, quante tolte, quante lasciate).
    """
    cartelle = conn.execute(
        "SELECT n.id, n.title FROM nodes n "
        "WHERE EXISTS (SELECT 1 FROM media m WHERE m.node_id = n.id "
        "              AND m.kind = 'image') "
        "  AND NOT EXISTS (SELECT 1 FROM media m WHERE m.node_id = n.id "
        "                  AND m.kind = 'image' "
        "                  AND m.ocr_stato NOT IN ('fatto', 'errore'))"
    ).fetchall()

    tolti: list[tuple[str, str, int, int]] = []
    for cartella in cartelle:
        con_numero = conn.execute(
            "SELECT COUNT(DISTINCT x.media_id) c FROM media_numeri x "
            "JOIN media m ON m.id = x.media_id WHERE m.node_id = ?",
            (cartella["id"],)).fetchone()["c"]
        if con_numero < minimo:
            continue

        righe = conn.execute(
            "SELECT x.id, x.numero, x.pos_x, x.pos_y FROM media_numeri x "
            "JOIN media m ON m.id = x.media_id "
            "WHERE m.node_id = ? AND x.origine = ? "
            "  AND x.pos_x IS NOT NULL AND x.pos_y IS NOT NULL",
            (cartella["id"], ORIGINE_OCR)).fetchall()

        per_numero: dict[str, list] = {}
        for r in righe:
            per_numero.setdefault(r["numero"], []).append(r)

        for numero, letture in per_numero.items():
            if len(letture) < minimo:
                continue
            cx = _mediana([r["pos_x"] for r in letture])
            cy = _mediana([r["pos_y"] for r in letture])
            fermi = [r for r in letture
                     if abs(r["pos_x"] - cx) <= raggio
                     and abs(r["pos_y"] - cy) <= raggio]
            if len(fermi) < minimo or len(fermi) / con_numero <= soglia:
                continue
            conn.executemany("DELETE FROM media_numeri WHERE id=?",
                             [(r["id"],) for r in fermi])
            tolti.append((cartella["title"], numero,
                          len(fermi), len(letture) - len(fermi)))
    return tolti


def ripulisci_podi(conn) -> int:
    """Toglie i numeri dei gradini del podio.

    Un podio si riconosce da due segnali che devono valere insieme:

    - nella stessa foto compaiono almeno DUE fra 1, 2 e 3 (i gradini);
    - non c'e' nessuna tabella, cioe' nessun numero a piu' cifre: sul podio
      i piloti sono scesi dalla bici, le tabelle non si vedono.

    Il secondo controllo e' quello che rende la regola sicura. Se in una
    gara i piloti con tabella 1, 2 e 3 finissero nella stessa inquadratura,
    con loro si vedrebbero anche le tabelle degli avversari, e la foto
    verrebbe lasciata stare.

    I numeri corretti a mano non si toccano.

    Returns:
        quante letture sono state tolte.
    """
    podi = [r["media_id"] for r in conn.execute(
        "SELECT media_id FROM media_numeri GROUP BY media_id "
        "HAVING SUM(CASE WHEN numero IN ('1','2','3') THEN 1 ELSE 0 END) >= 2 "
        "   AND SUM(CASE WHEN length(numero) > 1 THEN 1 ELSE 0 END) = 0"
    ).fetchall()]
    if not podi:
        return 0
    tolti = 0
    for i in range(0, len(podi), 400):        # a blocchi: la query ha un limite
        gruppo = podi[i:i + 400]
        segnaposto = ",".join("?" * len(gruppo))
        cur = conn.execute(
            f"DELETE FROM media_numeri WHERE length(numero) = 1 "
            f"AND origine = ? AND media_id IN ({segnaposto})",
            [ORIGINE_OCR, *gruppo])
        tolti += cur.rowcount or 0
    return tolti


def ripulisci_cifre_singole(conn, soglia: float = 0.15,
                            minimo: int = 5) -> list[tuple[str, str, int]]:
    """Toglie le cifre singole che sono cartelli dell'impianto, non tabelle.

    In certi impianti i settori delle tribune sono numerati con cifre grandi
    e nitide: l'OCR le legge con sicurezza altissima e nessuna soglia riesce
    a distinguerle da una tabella. Si distinguono pero' da COME si
    distribuiscono. Il numero di un pilota compare in poche foto della gara,
    quelle in cui c'e' lui; un cartello inquadrato di continuo compare in una
    grossa fetta delle foto della stessa cartella.

    Quindi, cartella per cartella, si scarta la cifra singola presente in
    piu' di `soglia` delle fotografie che hanno almeno un numero, purche' i
    casi siano almeno `minimo` (sotto, il campione e' troppo piccolo per
    dire qualcosa).

    Le correzioni fatte a mano non si toccano mai.

    Returns:
        elenco (titolo cartella, cifra, quante tolte).
    """
    # Solo cartelle interamente lette: su una cartella a meta' i conteggi
    # ingannano, e una tabella vera capitata nelle prime foto sembrerebbe
    # ricorrente.
    sospetti = conn.execute(
        "SELECT n.id AS node_id, n.title, x.numero, "
        "       COUNT(DISTINCT x.media_id) AS quante, "
        "       (SELECT COUNT(DISTINCT y.media_id) FROM media_numeri y "
        "        JOIN media m2 ON m2.id = y.media_id "
        "        WHERE m2.node_id = n.id) AS con_numero "
        "FROM media_numeri x "
        "JOIN media m ON m.id = x.media_id "
        "JOIN nodes n ON n.id = m.node_id "
        "WHERE length(x.numero) = 1 AND x.origine = ? "
        "  AND NOT EXISTS (SELECT 1 FROM media m3 WHERE m3.node_id = n.id "
        "                  AND m3.kind = 'image' "
        "                  AND m3.ocr_stato NOT IN ('fatto', 'errore')) "
        "GROUP BY n.id, x.numero",
        (ORIGINE_OCR,)).fetchall()

    tolti = []
    for r in sospetti:
        if r["quante"] < minimo or not r["con_numero"]:
            continue
        if r["quante"] / r["con_numero"] <= soglia:
            continue
        conn.execute(
            "DELETE FROM media_numeri WHERE numero = ? AND origine = ? "
            "AND media_id IN (SELECT id FROM media WHERE node_id = ?)",
            (r["numero"], ORIGINE_OCR, r["node_id"]))
        tolti.append((r["title"], r["numero"], r["quante"]))
    return tolti


def segna_stato(conn, media_id: int, stato: str) -> None:
    """Aggiorna lo stato di elaborazione di una foto."""
    conn.execute("UPDATE media SET ocr_stato=?, ocr_at=? WHERE id=?",
                 (stato, _adesso(), media_id))


def azzera_ocr(conn, media_id: int | None = None) -> None:
    """Rimette in coda una foto (o tutte) scartandone i numeri automatici."""
    if media_id is None:
        conn.execute("DELETE FROM media_numeri WHERE origine=?", (ORIGINE_OCR,))
        conn.execute("UPDATE media SET ocr_stato='', ocr_at=NULL WHERE kind='image'")
    else:
        conn.execute("DELETE FROM media_numeri WHERE media_id=? AND origine=?",
                     (media_id, ORIGINE_OCR))
        conn.execute("UPDATE media SET ocr_stato='', ocr_at=NULL WHERE id=?",
                     (media_id,))
