"""Lettura automatica dei numeri di gara sulle tabelle degli atleti.

Come funziona
-------------
1. si parte dalla miniatura grande gia' in cache (1800 px, su disco locale):
   e' molto piu' veloce che rileggere l'originale dal NAS. Se non c'e', si
   legge l'originale e lo si rimpicciolisce in memoria, senza scrivere
   nulla su disco;
2. il motore OCR restituisce i riquadri di testo trovati;
3. si tengono solo i riquadri che somigliano davvero a un numero di gara.

Il punto 3 e' quello che conta. In una foto di gara c'e' testo ovunque:
striscioni, sponsor, marchi sui caschi. Il numero sulla tabella pero' ha due
caratteristiche che il resto non ha: e' fatto di sole cifre ed e' grande. Si
scartano quindi i riquadri piu' bassi di OCR_MIN_HEIGHT_RATIO rispetto
all'altezza della foto e quelli letti con poca sicurezza.

L'elaborazione va in parallelo su piu' processi: il riconoscimento e'
lavoro di CPU pura, quindi i thread di Python non servirebbero a nulla. Il
numero di processi si calcola da solo in base ai core e alla memoria libera,
per non far mai mancare RAM al sito.

Motore
------
RapidOCR (modelli PP-OCR in formato ONNX): gratuito, gira in locale sulla
CPU, non manda nessuna fotografia su internet e non richiede chiavi.
Si installa con `pip install -r requirements-ocr.txt`. Senza, il sito
funziona identico e i numeri si inseriscono a mano dal pannello.
"""
import fcntl
import multiprocessing as mp
import os
import re
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from PIL import Image, ImageOps

from .config import get_settings
from .database import get_db, log_event, sottoalbero_like
from . import numeri as numeri_mod
from .numeri import normalizza, segna_stato, sostituisci_ocr

# Sequenze di cifre dentro il testo riconosciuto
_RE_CIFRE = re.compile(r"\d+")

# Stati della colonna media.ocr_stato:
#   ''          mai analizzata, in coda
#   'in_corso'  presa in carico da un'elaborazione
#   'fatto'     analizzata
#   'errore'    file illeggibile
_SCADUTA_DOPO = timedelta(hours=2)

# Motore del processo corrente. Nei processi figli viene creato una volta
# sola e riusato per tutte le foto che quel processo riceve.
_motore = None


class OCRNonDisponibile(RuntimeError):
    """Nessun motore OCR installato sul sistema."""


class LetturaGiaInCorso(RuntimeError):
    """C'e' gia' una lettura in corso in un altro processo."""


@contextmanager
def _lucchetto_di_sistema():
    """Garantisce UNA sola lettura per volta su tutta la macchina.

    Il lucchetto in memoria vale solo dentro il processo web. Qui serve un
    lucchetto vero su file, perche' la lettura puo' partire anche dal timer
    di sistema o dalla riga di comando: senza, due lavori si sommerebbero,
    ognuno con la propria squadra di processi, esaurendo la memoria e
    rallentando tutto invece di andare piu' veloce.
    """
    percorso = get_settings().data_path / "numeri.lock"
    file_lucchetto = open(percorso, "w")
    try:
        fcntl.flock(file_lucchetto, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        file_lucchetto.close()
        raise LetturaGiaInCorso("Lettura gia' in corso in un altro processo")
    try:
        yield
    finally:
        try:
            fcntl.flock(file_lucchetto, fcntl.LOCK_UN)
        finally:
            file_lucchetto.close()


# ---------------- Disponibilita' ----------------
def motore_installato() -> Optional[str]:
    """Nome del motore utilizzabile, None se non c'e'.

    Controlla solo che il pacchetto ci sia, senza caricare i modelli: si
    puo' chiamare a ogni apertura del pannello senza alcun costo.
    """
    import importlib.util
    if importlib.util.find_spec("rapidocr_onnxruntime") is not None:
        return "rapidocr"
    return None


def disponibile() -> bool:
    return motore_installato() is not None


def _carica_motore():
    """Crea il motore nel processo corrente (una volta sola)."""
    global _motore
    if _motore is None:
        if not disponibile():
            raise OCRNonDisponibile("Nessun motore OCR installato")
        from rapidocr_onnxruntime import RapidOCR
        # I thread vanno dichiarati: lasciati liberi, ogni processo ne
        # aprirebbe uno per core e con piu' processi in parallelo si
        # ostacolerebbero a vicenda. Uno per processo e' il massimo delle
        # prestazioni quando i processi sono gia' tanti.
        _motore = RapidOCR(intra_op_num_threads=1, inter_op_num_threads=1)
    return _motore


# ---------------- Analisi di una singola foto ----------------
def _prepara(percorso: Path, lato_max: int) -> Image.Image:
    """Apre l'immagine, la raddrizza secondo l'EXIF e la riduce per l'analisi."""
    with Image.open(percorso) as grezza:
        immagine = ImageOps.exif_transpose(grezza)
        if immagine.mode != "RGB":
            immagine = immagine.convert("RGB")
        if max(immagine.size) > lato_max:
            # draft accelera molto la lettura dei JPEG grandi: decodifica
            # direttamente a dimensione ridotta invece di aprire tutto
            if max(immagine.size) > lato_max * 3:
                immagine.draft("RGB", (lato_max * 2, lato_max * 2))
            immagine.thumbnail((lato_max, lato_max), Image.LANCZOS)
        immagine.load()
    return immagine


def leggi_numeri(percorso: Path, min_cifre: Optional[int] = None) -> list[tuple[str, float]]:
    """Legge i numeri di gara presenti in un'immagine.

    Args:
        percorso: file da analizzare.
        min_cifre: cifre minime accettate; None per il valore predefinito.
            Serve a escludere le cifre singole dove sono numeri di corsia.

    Restituisce quaterne (numero, sicurezza, centro x, centro y, altezza)
    con le coordinate espresse da 0 a 1, senza duplicati e dalla lettura
    piu' affidabile alla meno affidabile. La posizione serve poi a capire
    se un numero e' una tabella che si muove o un cartello fisso.
    """
    import numpy as np

    motore = _carica_motore()
    impostazioni = get_settings()
    if min_cifre is None:
        min_cifre = impostazioni.ocr_min_digits
    immagine = _prepara(Path(percorso), impostazioni.ocr_max_side)
    altezza_minima = immagine.height * impostazioni.ocr_min_height_ratio

    # RapidOCR e' costruito su OpenCV e vuole i canali in ordine BGR
    risultato, _tempi = motore(np.asarray(immagine)[:, :, ::-1])

    # numero -> (sicurezza, centro x, centro y, altezza) tutti in 0-1
    migliori: dict[str, tuple[float, float, float, float]] = {}
    for riquadro, testo, sicurezza in (risultato or []):
        sicurezza = float(sicurezza)
        if sicurezza < impostazioni.ocr_min_confidence:
            continue

        ys = [punto[1] for punto in riquadro]
        if (max(ys) - min(ys)) < altezza_minima:
            continue

        # Il vero segno distintivo di una tabella non e' la dimensione (nelle
        # foto d'azione i piloti lontani hanno tabelle minuscole) ma il fatto
        # che ci siano scritte SOLO cifre. Tutto il resto del testo che
        # popola una foto di gara - "heusden", "alecycling.com",
        # "2024 BMX EUROPEAN CUP", "ESORDIENTI1M" - contiene lettere o segni
        # e viene scartato qui.
        pulito = "".join(testo.split())
        if not pulito.isdigit():
            continue
        # Si guarda la lunghezza scritta, non quella normalizzata: "007" e'
        # una tabella a tre cifre, non un numero di corsia.
        if not (min_cifre <= len(pulito) <= impostazioni.ocr_max_digits):
            continue

        valore = normalizza(pulito)
        if valore is None:
            continue
        # Gli anni sui cartelloni sono l'unico numero puro che ricorre di
        # continuo senza essere una tabella.
        if len(pulito) == 4 and 1900 <= int(valore) <= 2099:
            continue

        xs = [punto[0] for punto in riquadro]
        if sicurezza > migliori.get(valore, (0.0,))[0]:
            migliori[valore] = (
                sicurezza,
                (min(xs) + max(xs)) / 2 / immagine.width,
                (min(ys) + max(ys)) / 2 / immagine.height,
                (max(ys) - min(ys)) / immagine.height,
            )

    return sorted(((n, *v) for n, v in migliori.items()),
                  key=lambda v: v[1], reverse=True)


# ---------------- Lavoro in parallelo ----------------
def _sorgente(rel_path: str, mtime: float) -> Path:
    """Percorso da leggere: la miniatura grande se c'e', altrimenti l'originale.

    Non genera miniature mancanti di proposito: crearle tutte occuperebbe
    parecchi gigabyte di disco per un vantaggio che si ha una volta sola.
    """
    from .thumbnails import _cache_file, _cache_key, SIZE_MEDIUM
    miniatura = _cache_file(_cache_key(rel_path, mtime, SIZE_MEDIUM))
    if miniatura.exists():
        return miniatura
    return get_settings().photo_root_path / rel_path


def _min_cifre_per(rel_path: str) -> int:
    """Cifre minime accettate per una foto, in base alla cartella.

    Dove le cifre singole sono numeri di corsia e non tabelle (atletica) si
    alza il minimo a due; altrove le tabelle da 1 a 9 sono valide.
    """
    elenco = (get_settings().ocr_niente_cifre_singole or "").strip()
    if not elenco:
        return get_settings().ocr_min_digits
    percorso = rel_path.lower()
    for voce in elenco.split(","):
        voce = voce.strip().lower()
        if voce and (percorso == voce or percorso.startswith(voce + "/")):
            return max(2, get_settings().ocr_min_digits)
    return get_settings().ocr_min_digits


def _lavora(compito):
    """Eseguito nei processi figli: analizza una foto e torna cio' che ha letto."""
    media_id, percorso, min_cifre = compito
    try:
        return media_id, leggi_numeri(Path(percorso), min_cifre), None
    except Exception as errore:
        return media_id, [], str(errore)[:200]


def processi_consigliati() -> int:
    """Quanti processi usare: il massimo che core e memoria libera reggono.

    Ogni processo occupa circa 250 MB. Si lascia sempre un core e un po' di
    memoria al sito, che deve continuare a rispondere ai visitatori mentre
    l'analisi lavora.
    """
    impostazioni = get_settings()
    if impostazioni.ocr_workers > 0:
        return impostazioni.ocr_workers

    core = max(1, (os.cpu_count() or 2) - 2)

    libera_mb = 1024
    try:
        for riga in Path("/proc/meminfo").read_text().splitlines():
            if riga.startswith("MemAvailable:"):
                libera_mb = int(riga.split()[1]) / 1024
                break
    except OSError:
        pass
    # 700 MB restano al sito e al sistema: se finisse la memoria, il servizio
    # web verrebbe ucciso e il sito andrebbe giu'.
    per_memoria = max(1, int((libera_mb - 700) // impostazioni.ocr_mb_per_worker))

    return max(1, min(core, per_memoria, 16))


def _recupera_bloccate(conn) -> None:
    """Rimette in coda le foto rimaste 'in_corso' dopo un'interruzione."""
    soglia = (datetime.now(timezone.utc) - _SCADUTA_DOPO).isoformat()
    conn.execute("UPDATE media SET ocr_stato='' WHERE ocr_stato='in_corso' "
                 "AND (ocr_at IS NULL OR ocr_at < ?)", (soglia,))


def _recupera_tutte(conn) -> int:
    """Rimette in coda TUTTE le foto lasciate a meta'.

    Si chiama solo dopo aver preso il lucchetto di sistema: in quel momento
    nessun altro processo puo' starci lavorando, quindi ogni foto ancora
    'in_corso' e' il residuo di un'interruzione (riavvio del container,
    aggiornamento, spegnimento). Cosi' la lettura riprende esattamente da
    dove era arrivata, senza aspettare la scadenza delle due ore.

    Restituisce quante ne ha recuperate. Non scrive nel registro da qui:
    log_event apre una connessione propria e resterebbe in attesa di questa
    transazione, bloccandosi da sola.
    """
    return conn.execute(
        "UPDATE media SET ocr_stato='' WHERE ocr_stato='in_corso'").rowcount


def in_coda() -> int:
    """Quante immagini sono ancora da analizzare."""
    with get_db() as conn:
        return conn.execute("SELECT COUNT(*) c FROM media "
                            "WHERE kind='image' AND ocr_stato=''").fetchone()["c"]


def _prendi_in_carico(quante: int) -> list[tuple[int, str]]:
    """Riserva un blocco di foto da analizzare.

    Segnarle come 'in_corso' prima di iniziare evita che il timer di sistema
    e un'elaborazione lanciata dal pannello lavorino sulle stesse foto.
    """
    priorita = (get_settings().ocr_priorita or "").strip()
    with get_db() as conn:
        _recupera_bloccate(conn)
        if priorita:
            righe = conn.execute(
                "SELECT m.id, m.rel_path, m.mtime FROM media m "
                "JOIN nodes n ON n.id = m.node_id "
                "WHERE m.kind='image' AND m.ocr_stato='' "
                "ORDER BY CASE WHEN n.rel_path = ? OR n.rel_path LIKE ? ESCAPE '\\' "
                "         THEN 0 ELSE 1 END, m.mtime DESC LIMIT ?",
                (priorita, sottoalbero_like(priorita), quante)).fetchall()
        else:
            righe = conn.execute(
                "SELECT id, rel_path, mtime FROM media "
                "WHERE kind='image' AND ocr_stato='' "
                "ORDER BY mtime DESC LIMIT ?",
                (quante,)).fetchall()
        if not righe:
            return []
        ids = [r["id"] for r in righe]
        segnaposto = ",".join("?" * len(ids))
        conn.execute(
            f"UPDATE media SET ocr_stato='in_corso', ocr_at=? "
            f"WHERE id IN ({segnaposto}) AND ocr_stato=''",
            [datetime.now(timezone.utc).isoformat(), *ids])
    return [(r["id"], str(_sorgente(r["rel_path"], r["mtime"])),
             _min_cifre_per(r["rel_path"])) for r in righe]


def elabora(limite: Optional[int] = None, processi: Optional[int] = None,
            avanzamento: Optional[Callable[[dict], None]] = None) -> dict:
    """Analizza le foto in coda e registra i numeri trovati.

    Args:
        limite: quante foto al massimo; None per svuotare tutta la coda.
        processi: quanti processi in parallelo; None per deciderlo da solo.
        avanzamento: funzione chiamata dopo ogni blocco, riceve i contatori.
    """
    impostazioni = get_settings()
    esito = {"analizzate": 0, "con_numero": 0, "numeri": 0, "errori": 0,
             "in_coda": 0, "processi": 0}

    if not impostazioni.ocr_enabled:
        esito["in_coda"] = in_coda()
        return esito
    if not disponibile():
        esito["in_coda"] = in_coda()
        log_event("WARNING", "ocr", "Nessun motore OCR installato")
        return esito

    n_processi = processi or processi_consigliati()
    esito["processi"] = n_processi
    blocco = max(n_processi * 8, 32)

    try:
        with _lucchetto_di_sistema():
            # Preso il lucchetto, nessun altro sta lavorando: quello che
            # risulta ancora "in corso" e' rimasto da un'interruzione e va
            # rimesso subito in coda.
            with get_db() as conn:
                riprese = _recupera_tutte(conn)
            if riprese:
                log_event("INFO", "ocr",
                          f"Riprese {riprese} foto lasciate a meta'")
            _cicla(esito, n_processi, blocco, limite, avanzamento)
    except LetturaGiaInCorso:
        esito["in_coda"] = in_coda()
        esito["saltato"] = True
        log_event("INFO", "ocr", "Lettura gia' in corso: questa passata si ferma")
        return esito

    # A lettura conclusa si tolgono i numeri che sono cartelli fissi
    # dell'impianto: si riconoscono perche' ricadono sempre nello stesso
    # punto dell'inquadratura, e serve avere i dati di tutta la cartella
    # per accorgersene.
    with get_db() as conn:
        podi = numeri_mod.ripulisci_podi(conn)
        tolti = numeri_mod.ripulisci_cartelli(conn)
    if podi:
        log_event("INFO", "ocr",
                  f"Tolte {podi} letture dai gradini dei podi")
    esito["podi_scartati"] = podi
    for titolo, numero, quanti, lasciati in tolti:
        log_event("INFO", "ocr",
                  f"Numero '{numero}' scartato in '{titolo}': {quanti} letture "
                  f"sempre nello stesso punto (cartello dell'impianto)"
                  + (f"; {lasciati} lasciate, erano altrove" if lasciati else ""))
    esito["cartelli_scartati"] = len(tolti)

    esito["in_coda"] = in_coda()
    log_event("INFO", "ocr", f"Lettura numeri: {esito}")
    return esito


def _cicla(esito: dict, n_processi: int, blocco: int, limite: Optional[int],
           avanzamento: Optional[Callable[[dict], None]]) -> None:
    """Svuota la coda a blocchi, distribuendo il lavoro sui processi."""
    restanti = limite
    # spawn invece di fork: i processi figli partono puliti, senza ereditare
    # connessioni al database o stato del sito
    pool = mp.get_context("spawn").Pool(processes=n_processi)
    try:
        while restanti is None or restanti > 0:
            quante = blocco if restanti is None else min(blocco, restanti)
            compiti = _prendi_in_carico(quante)
            if not compiti:
                break

            risultati = pool.map(_lavora, compiti)

            with get_db() as conn:
                for media_id, letture, errore in risultati:
                    if errore is None:
                        scritti = sostituisci_ocr(conn, media_id, letture)
                        if scritti:
                            esito["con_numero"] += 1
                            esito["numeri"] += scritti
                        segna_stato(conn, media_id, "fatto")
                    else:
                        esito["errori"] += 1
                        segna_stato(conn, media_id, "errore")
                    esito["analizzate"] += 1

            if restanti is not None:
                restanti -= len(compiti)
            if avanzamento:
                avanzamento(dict(esito))
    finally:
        pool.close()
        pool.join()


# ---------------- Avvio dal pannello ----------------
# Il pannello puo' far partire l'analisi dell'intero archivio senza bloccare
# la pagina: su decine di migliaia di foto ci vuole parecchio. Il lucchetto
# garantisce che ne parta una sola per volta.
_lucchetto = threading.Lock()
_stato: dict = {"attivo": False, "analizzate": 0, "totale": 0,
                "con_numero": 0, "errori": 0, "processi": 0, "finito_alle": None}

# L'avanzamento si scrive anche su file, accanto al lucchetto.
#
# Il sito gira su piu' processi: la richiesta che fa partire la lettura e
# quella che poi chiede "a che punto siamo" possono finire su due processi
# diversi. Tenendo l'avanzamento solo in memoria, il pannello mostrerebbe
# "nessun lavoro in corso" mentre il lavoro sta girando accanto, e chi
# guarda lo farebbe ripartire credendo che non fosse mai partito.
_FILE_STATO = "numeri.stato"


def _percorso_stato():
    return get_settings().data_path / _FILE_STATO


def _scrivi_stato() -> None:
    import json
    try:
        percorso = _percorso_stato()
        provvisorio = percorso.with_suffix(".tmp")
        provvisorio.write_text(json.dumps(_stato), encoding="utf-8")
        provvisorio.replace(percorso)
    except OSError:
        pass


def stato_lavoro() -> dict:
    """Avanzamento della lettura, da qualunque processo lo si chieda."""
    import json
    if _stato["attivo"]:
        return dict(_stato)          # lo stiamo facendo noi: e' il piu' fresco
    try:
        salvato = json.loads(_percorso_stato().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(_stato)
    if not isinstance(salvato, dict):
        return dict(_stato)
    # Se il file dice "in corso" ma nessuno tiene il lucchetto, il lavoro e'
    # finito male (processo interrotto): non si lascia il pannello a
    # mostrare un avanzamento fermo per sempre.
    if salvato.get("attivo") and not lettura_in_corso():
        salvato["attivo"] = False
    return salvato


def lettura_in_corso() -> bool:
    """Vero se qualcuno, in qualsiasi processo, sta leggendo i numeri."""
    percorso = get_settings().data_path / "numeri.lock"
    try:
        with open(percorso, "w") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return True          # lo tiene qualcun altro
            fcntl.flock(f, fcntl.LOCK_UN)
            return False
    except OSError:
        return False


def avvia_in_sottofondo() -> bool:
    """Fa partire l'analisi in un thread. False se ce n'e' gia' una in corso."""
    if not _lucchetto.acquire(blocking=False):
        return False
    _stato.update(attivo=True, analizzate=0, con_numero=0, errori=0,
                  totale=in_coda(), processi=processi_consigliati(),
                  finito_alle=None)
    _scrivi_stato()
    threading.Thread(target=_gira_in_sottofondo, name="ocr", daemon=True).start()
    return True


def _gira_in_sottofondo() -> None:
    def avanzamento(dati: dict) -> None:
        _stato.update(analizzate=dati["analizzate"], con_numero=dati["con_numero"],
                      errori=dati["errori"])
        _scrivi_stato()

    try:
        elabora(limite=None, avanzamento=avanzamento)
    except Exception as errore:
        log_event("ERROR", "ocr", f"Lettura numeri interrotta: {errore}")
    finally:
        _stato["attivo"] = False
        _stato["finito_alle"] = datetime.now(timezone.utc).isoformat()
        _scrivi_stato()
        _lucchetto.release()
