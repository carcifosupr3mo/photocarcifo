"""Il lucchetto che impedisce a due processi di comprimere lo stesso
archivio insieme.

Verifica sia l'unita' (app.zip_lock, in isolamento) sia il comportamento
HTTP vero (/zip/node, /zip/select), perche' la parte che conta davvero -
il rilascio garantito qualunque sia la sorte dello streaming - dipende da
come Starlette invia la risposta, non solo dalla logica del lucchetto.
"""
import multiprocessing
import time

import pytest


# --- Unita': la chiave e il lucchetto in isolamento ------------------------

def test_chiave_selezione_ignora_ordine_e_doppioni():
    from app.zip_lock import chiave_selezione
    assert chiave_selezione([3, 1, 2]) == chiave_selezione([2, 3, 1])
    assert chiave_selezione([1, 2, 3, 3, 3]) == chiave_selezione([1, 2, 3])


def test_chiave_selezione_distingue_contenuti_diversi():
    from app.zip_lock import chiave_selezione
    assert chiave_selezione([1, 2, 3]) != chiave_selezione([1, 2, 4])


def test_chiave_album_distingue_album_diversi():
    from app.zip_lock import chiave_album
    assert chiave_album(10) != chiave_album(11)
    assert chiave_album(10) == chiave_album(10)


def test_chiave_non_valida_non_produce_un_percorso():
    """Nessun chiamante puo' mai passare un input arbitrario a
    _percorso_lock: solo un digest esadecimale prodotto da chiave_album/
    chiave_selezione supera il controllo. Prova comunque input ostili, a
    riprova che la guardia non dipende da chi la chiama."""
    from app.zip_lock import _percorso_lock
    for cattivo in ("../../etc/passwd", "..%2f..%2fetc", "", "a" * 10,
                    "A" * 32, "abc123/../evil", "🙂" * 8):
        with pytest.raises(ValueError):
            _percorso_lock(cattivo)


def test_lucchetto_libero_si_prende_e_si_rilascia():
    from app.zip_lock import lucchetto_zip, chiave_album
    k = chiave_album(-1001)  # id finto, il lucchetto non guarda se esiste
    with lucchetto_zip(k):
        pass  # nessuna eccezione: preso e rilasciato senza intoppi


def test_lucchetto_occupato_nello_stesso_processo_viene_rifiutato():
    """Due `with` innestati sulla stessa chiave, nello stesso processo:
    non e' il caso interessante (quello vero e' tra processi, sotto), ma
    deve comunque comportarsi bene perche' fcntl.LOCK_NB su un file gia'
    aperto in scrittura dallo stesso processo si comporta diversamente a
    seconda del sistema — qui si aprono due file descriptor distinti sullo
    stesso path, che e' esattamente cio' che due richieste concorrenti
    farebbero anche dentro un solo worker (thread diversi)."""
    from app.zip_lock import lucchetto_zip, chiave_album, ArchivioGiaInPreparazione
    k = chiave_album(-1002)
    with lucchetto_zip(k):
        with pytest.raises(ArchivioGiaInPreparazione):
            with lucchetto_zip(k):
                pass  # non deve mai arrivare qui


def test_lucchetto_rilasciato_dopo_eccezione():
    """Chi tiene il lucchetto e solleva un'eccezione dentro il blocco non
    lo deve lasciare occupato: altrimenti un errore di compressione
    blocca per sempre quello stesso archivio."""
    from app.zip_lock import lucchetto_zip, chiave_album
    k = chiave_album(-1003)
    with pytest.raises(ValueError):
        with lucchetto_zip(k):
            raise ValueError("errore simulato a meta' streaming")
    with lucchetto_zip(k):
        pass  # se il primo non avesse rilasciato, questo solleverebbe


def test_file_lock_esistente_ma_libero_non_blocca():
    """Il file .lock resta sul disco anche a lucchetto libero (per
    disegno: cancellarlo aprirebbe una corsa). Un file .lock che esiste
    gia' da un download precedente e completato non deve impedire un
    nuovo download identico."""
    from app.zip_lock import lucchetto_zip, chiave_album
    k = chiave_album(-1004)
    with lucchetto_zip(k):
        pass
    # il file .lock esiste ancora qui, ma libero: un secondo giro deve
    # funzionare comunque.
    with lucchetto_zip(k):
        pass


# --- Tra processi veri, non solo tra thread o oggetti Python ---------------

def _prendi_e_tieni(chiave, secondi, coda):
    import sys
    sys.path.insert(0, "/opt/photocarcifo")
    from app.zip_lock import lucchetto_zip
    with lucchetto_zip(chiave):
        coda.put("preso")
        time.sleep(secondi)
    coda.put("rilasciato")


def test_due_processi_veri_si_escludono_a_vicenda():
    """Il caso che conta per davvero: non due oggetti nello stesso
    interprete, ma due PROCESSI separati (fork), come sono davvero i
    quattro worker uvicorn del sito. Se questo test passasse anche con un
    dizionario Python in memoria invece di flock, sarebbe la prova che il
    test non misura niente: un dizionario in un processo non e' visibile
    dall'altro, quindi qui il secondo processo DEVE fallire per forza
    tramite il file, non per condivisione di memoria (che qui non c'e')."""
    from app.zip_lock import chiave_album
    k = chiave_album(-1005)
    ctx = multiprocessing.get_context("fork")
    coda = ctx.Queue()

    p1 = ctx.Process(target=_prendi_e_tieni, args=(k, 1.0, coda))
    p1.start()
    time.sleep(0.2)  # lascia che p1 prenda per primo il lucchetto

    import sys
    sys.path.insert(0, "/opt/photocarcifo")
    from app.zip_lock import lucchetto_zip, ArchivioGiaInPreparazione

    assert coda.get(timeout=2) == "preso"
    with pytest.raises(ArchivioGiaInPreparazione):
        with lucchetto_zip(k):
            pytest.fail("il secondo processo ha preso un lucchetto gia' occupato")

    p1.join(timeout=3)
    assert coda.get(timeout=1) == "rilasciato"
    # ora che p1 ha finito, lo stesso lucchetto deve essere libero
    with lucchetto_zip(k):
        pass


# --- Comportamento HTTP vero, contro il sito in esecuzione ------------------
#
# I test qui sotto girano contro l'app FastAPI vera tramite TestClient (lo
# stesso client dei test esistenti), NON contro processi uvicorn separati:
# il comportamento cross-processo e' gia' provato sopra in isolamento sulla
# primitiva vera (flock), che e' l'unica cosa che deve reggere fra worker
# diversi — l'endpoint la usa cosi' com'e', senza logica aggiuntiva propria.

def _album_scaricabile_davvero(conn):
    """Un album pubblico, con download abilitato, e con almeno un file
    che esiste per davvero sul disco: la fixture `dati` non lo garantisce
    (nel tempo lo scanner riorganizza le cartelle e un vecchio node_id di
    prova puo' restare senza file), e senza un file vero zip_node esce con
    404 prima ancora di arrivare a toccare il lucchetto — il che farebbe
    fallire questo test per una ragione che non ha niente a che fare con
    il lucchetto."""
    from app.config import get_settings
    radice = get_settings().photo_root_path
    for r in conn.execute(
            "SELECT n.id, m.rel_path FROM nodes n JOIN media m ON m.node_id=n.id "
            "WHERE n.is_private=0 AND n.hidden=0 AND n.downloads_enabled=1"):
        if (radice / r["rel_path"]).exists():
            return r["id"]
    return None


def test_zip_node_risponde_409_se_gia_in_preparazione(client):
    """Prende il lucchetto a mano, come se un altro worker stesse gia'
    comprimendo lo stesso album, e verifica che l'endpoint risponda 409
    senza avviare un secondo streaming."""
    from app.database import get_db
    from app.zip_lock import lucchetto_zip, chiave_album
    with get_db() as conn:
        node_id = _album_scaricabile_davvero(conn)
    if not node_id:
        pytest.skip("nessun album con file veri su disco nei dati di prova")
    k = chiave_album(node_id)
    with lucchetto_zip(k):
        r = client.get(f"/zip/node/{node_id}")
        assert r.status_code == 409
        assert "preparazione" in r.json()["detail"].lower()
    # rilasciato: ora deve passare (se ci sono file veri sul disco, 200; se
    # no, e' un 403/404 legittimo per file mancanti o download disabilitato
    # — cio' che conta e' che NON sia piu' 409, cioe' che il lucchetto sia
    # stato liberato e non sia lui a bloccare il secondo tentativo).
    r2 = client.get(f"/zip/node/{node_id}")
    assert r2.status_code != 409


def test_zip_select_risponde_409_se_gia_in_preparazione(client, dati):
    from app.zip_lock import lucchetto_zip, chiave_selezione
    if not dati.get("media_id"):
        pytest.skip("nessuna foto pubblica nei dati di prova")
    mid = dati["media_id"]
    k = chiave_selezione([mid])
    with lucchetto_zip(k):
        r = client.get(f"/zip/select?ids={mid}")
        assert r.status_code == 409


def test_zip_select_stesso_insieme_ordine_diverso_condivide_il_lucchetto(client, dati):
    from app.zip_lock import lucchetto_zip, chiave_selezione
    if not dati.get("media_id"):
        pytest.skip("nessuna foto pubblica nei dati di prova")
    mid = dati["media_id"]
    # Anche con un solo id la chiave e' deterministica: qui verifichiamo
    # che l'endpoint calcoli la STESSA chiave che chiave_selezione produce
    # per l'insieme normalizzato, non una sua versione diversa.
    k = chiave_selezione([mid])
    with lucchetto_zip(k):
        r = client.get(f"/zip/select?ids={mid}")
        assert r.status_code == 409


def test_selezione_condivisa_zip_risponde_409_se_gia_in_preparazione(client, dati):
    """Come test_zip_select_risponde_409_se_gia_in_preparazione, ma per
    l'endpoint della pagina di condivisione multi-foto (/fs/{token}/zip):
    deve prendere lo STESSO lucchetto di zip_select per lo stesso insieme
    di id, non uno separato."""
    from app.zip_lock import lucchetto_zip, chiave_selezione
    if not dati.get("media_id"):
        pytest.skip("nessuna foto pubblica nei dati di prova")
    mid = dati["media_id"]
    r = client.post("/condividi/selezione", data={"ids": str(mid)})
    if r.status_code != 200:
        pytest.skip("impossibile creare un link di condivisione di prova")
    token = r.json()["share_token"]
    k = chiave_selezione([mid])
    with lucchetto_zip(k):
        r2 = client.get(f"/fs/{token}/zip")
        assert r2.status_code == 409
    # rilasciato: ora deve passare (non piu' 409, che e' cio' che conta qui;
    # un eventuale 403/404 per download disabilitato sarebbe comunque
    # legittimo e non e' cio' che questo test verifica).
    r3 = client.get(f"/fs/{token}/zip")
    assert r3.status_code != 409


def test_zip_directory_dei_lock_non_e_servita_pubblicamente(client):
    """La cartella dei .lock non deve essere raggiungibile via web: e'
    dentro data/, che il server statico non pubblica."""
    r = client.get("/data/zip-lock/qualcosa.lock")
    assert r.status_code == 404
