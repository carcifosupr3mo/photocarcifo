"""Un solo processo alla volta prepara lo stesso archivio ZIP.

Lo stesso schema di app/ocr.py (_lucchetto_di_sistema): un file vero su
disco invece di un dizionario in Python, perche' il sito gira su quattro
processi uvicorn separati (vedi deploy: --workers 4) e un dizionario in
memoria varrebbe solo dentro il processo che l'ha scritto — la richiesta
sul processo accanto non lo vedrebbe mai, ed e' esattamente il buco che
ARCHIVI_IN_CORSO lascia aperto lato client: protegge il doppio click sulla
stessa pagina, non due schede, due finestre o due persone diverse.

Cosa succede a un archivio uguale, gia' verificato provando il
comportamento vero di StreamingResponse (non solo leggendolo):
  - il generatore che costruisce lo ZIP puo' restare sospeso per sempre se
    il client si disconnette a meta' (Starlette non lo richiude mai, lo
    smette solo di interrogare): un finally scritto DENTRO il generatore
    non e' una garanzia;
  - se il generatore solleva un'eccezione, il "background" di Starlette
    (il posto pensato apposta per un rilascio a fine risposta) non parte:
    l'eccezione lo scavalca.
  Il rilascio quindi non sta nel generatore ne' in un background: sta in
  un try/finally intorno all'INVIO della risposta stessa (vedi
  RispostaZipConLucchetto piu' sotto in media.py), l'unico punto che nei
  tre casi provati (successo, errore, disconnessione) scatta sempre.
"""
import fcntl
import hashlib
import re
from contextlib import contextmanager
from pathlib import Path

from .config import get_settings

# Un nome di file fatto solo di lettere e cifre esadecimali: la chiave del
# lock nasce sempre da un digest, mai da input dell'utente messo diretto
# nel percorso. Questo controllo e' solo una rete in piu' — chi chiama
# chiave_selezione()/chiave_album() non puo' comunque produrre altro.
_NOME_VALIDO = re.compile(r"^[0-9a-f]{16,64}$")


class ArchivioGiaInPreparazione(RuntimeError):
    """C'e' gia' un altro processo che sta preparando lo stesso archivio."""


def chiave_album(node_id: int) -> str:
    """Due richieste per lo stesso album (stesso node_id) sono lo stesso
    archivio: il contenuto della cartella tra una richiesta e l'altra non
    cambia a meta' streaming, quindi basta l'identificativo."""
    return hashlib.sha256(f"album:{int(node_id)}".encode()).hexdigest()[:32]


def chiave_selezione(id_list) -> str:
    """Due selezioni con gli stessi identificativi, in qualsiasi ordine e
    con eventuali doppioni, sono lo stesso archivio: [1,2,3] e [3,2,1]
    producono file identici, byte per byte. Si ordina e si deduplica prima
    di calcolare l'impronta, cosi' le due richieste condividono la stessa
    chiave invece di aprire due lucchetti diversi per lo stesso lavoro.

    id_list deve gia' essere la lista di interi validati (vedi
    _ids_da_elenco): qui non si rifa' la validazione, solo la normalizza-
    zione che serve a riconoscere due selezioni uguali."""
    normalizzati = sorted(set(int(i) for i in id_list))
    testo = ",".join(str(i) for i in normalizzati)
    return hashlib.sha256(testo.encode()).hexdigest()[:32]


def _percorso_lock(chiave: str) -> Path:
    if not _NOME_VALIDO.match(chiave):
        # Non dovrebbe mai succedere (le due funzioni sopra producono
        # sempre un digest esadecimale): se succede e' un errore di
        # programmazione da un chiamante nuovo, non un input malevolo da
        # accettare in silenzio.
        raise ValueError(f"chiave di lock non valida: {chiave!r}")
    cartella = get_settings().data_path / "zip-lock"
    cartella.mkdir(exist_ok=True)
    return cartella / f"{chiave}.lock"


@contextmanager
def lucchetto_zip(chiave: str):
    """Un solo streaming alla volta per la stessa chiave, su tutta la
    macchina (funziona fra i quattro processi uvicorn, non solo dentro
    uno). Se un altro processo ha gia' il lucchetto, solleva
    ArchivioGiaInPreparazione subito, senza aprire nessun file e senza
    avviare _zip_stream: il chiamante la trasforma in 409.

    Il file .lock puo' restare sul disco anche a lucchetto libero (non lo
    si cancella mai): cancellarlo aprirebbe una corsa fra chi lo libera e
    chi in quell'istante lo sta aprendo per prenderlo, e non serve a
    niente — flock non guarda se il file e' "nuovo", guarda se qualcuno
    lo tiene aperto in stato di lucchetto preso. Un file vuoto che resta
    li' e' innocuo quanto un lucchetto vuoto appeso alla porta."""
    percorso = _percorso_lock(chiave)
    file_lucchetto = open(percorso, "w")
    try:
        fcntl.flock(file_lucchetto, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        file_lucchetto.close()
        raise ArchivioGiaInPreparazione(
            "Questo archivio e' gia' in preparazione")
    try:
        yield
    finally:
        try:
            fcntl.flock(file_lucchetto, fcntl.LOCK_UN)
        finally:
            file_lucchetto.close()
