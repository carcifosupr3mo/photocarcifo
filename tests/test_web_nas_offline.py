"""Un visitatore non deve mai vedere uno stacktrace grezzo, e il database
non deve mai essere alterato, quando il NAS e' irraggiungibile mentre una
richiesta web e' in corso. Qui si simula "file DB valido, filesystem non
disponibile" con monkeypatch su photo_root — nessuno smonta il NAS vero.
Vedi PROJECT_KNOWLEDGE.md, sezione 12 (Scanner) per il bug gemello gia'
risolto lato scanner; questo file copre invece le rotte web di
media/download/ZIP/condivisione.

Nota su use_xaccel (default True, vedi app/config.py): in produzione
download/video non aprono mai il file da Python. Rispondono 200 con
l'header X-Accel-Redirect e lasciano a nginx (location /_originals/,
alias sul mount NFS, con error_page 404 -> proxy verso l'app, verificato
in /etc/nginx/sites-enabled/photocarcifo) il compito di rispondere 404 se
il file non e' raggiungibile. Il TestClient non e' nginx: con
use_xaccel=True vede correttamente 200+header, non un 404. Per questo
ogni rotta protetta da X-Accel ha due test — uno per il comportamento
reale di produzione, uno per il fallback locale (use_xaccel=False) che
apre davvero il file.
"""
import sqlite3
import tempfile
from pathlib import Path

import pytest


def _conteggi():
    from app.config import get_settings
    conn = sqlite3.connect(str(get_settings().db_path))
    n = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    m = conn.execute("SELECT COUNT(*) FROM media").fetchone()[0]
    c = conn.execute("SELECT COUNT(*) FROM condivisioni").fetchone()[0]
    conn.close()
    return n, m, c


@pytest.fixture
def nas_irraggiungibile(monkeypatch):
    """Sposta photo_root su una cartella locale vuota: ogni file che il DB
    conosce risulta 'non trovato' esattamente come lo vedrebbe il codice
    con un NAS staccato (stesso sintomo di app.scanner._nas_disponibile:
    .exists() torna False su ogni percorso, senza sollevare eccezioni di
    I/O). Usa una cartella vera (non un path fantasma) cosi' anche
    os.stat() dentro Starlette si comporta come su un filesystem
    raggiungibile ma senza quel file — il caso 'file DB valido, filesystem
    non disponibile' richiesto dal task."""
    from app.config import get_settings
    with tempfile.TemporaryDirectory() as tmp:
        settings = get_settings()
        originale = settings.photo_root
        monkeypatch.setattr(settings, "photo_root", tmp)
        yield Path(tmp)
        monkeypatch.setattr(settings, "photo_root", originale)


def _pulisci_cache_per(media_id: int):
    """Rimuove qualunque miniatura gia' in cache per questo media, cosi'
    il test forza davvero un tentativo di lettura dal (finto) NAS invece
    di trovare una miniatura vecchia gia' pronta su disco locale."""
    from app.config import get_settings
    from app.database import get_db
    with get_db() as conn:
        row = conn.execute("SELECT rel_path, mtime, kind FROM media WHERE id=?",
                           (media_id,)).fetchone()
    if not row:
        return
    import app.thumbnails as th
    for size in (th.SIZE_SMALL, th.SIZE_CARD, th.SIZE_MEDIUM, th.SIZE_COVER, th.SIZE_SOCIAL):
        for formato in (th.FORMATO_JPEG, th.FORMATO_WEBP, th.FORMATO_AVIF):
            key = th._cache_key(row["rel_path"], row["mtime"], size, formato)
            f = th._cache_file(key, formato)
            if f.exists():
                f.unlink()


class TestThumbnailNasOffline:
    def test_thumbnail_file_valido_nas_irraggiungibile(self, client, dati, nas_irraggiungibile):
        media_id = dati["media_id"]
        assert media_id, "precondizione: serve una foto pubblica vera nel DB"
        _pulisci_cache_per(media_id)
        r = client.get(f"/thumb/{media_id}")
        # Nessun 500 grezzo: la cache manca, il file non e' raggiungibile,
        # get_or_create_thumbnail ritorna None -> 404 gestito.
        assert r.status_code == 404
        assert "Traceback" not in r.text


class TestDownloadNasOffline:
    def test_download_xaccel_delega_a_nginx_senza_toccare_il_filesystem(
            self, client, dati, nas_irraggiungibile):
        """Configurazione reale di produzione: FastAPI non apre mai il
        file, risponde 200 con X-Accel-Redirect e lascia a nginx il
        404 se il file non c'e'. Qui si verifica solo la parte di
        competenza di FastAPI: nessuna eccezione, nessun 500."""
        media_id = dati["media_id"]
        assert media_id
        r = client.get(f"/download/{media_id}")
        assert r.status_code == 200
        assert "x-accel-redirect" in {k.lower() for k in r.headers.keys()}
        assert "Traceback" not in r.text

    def test_download_senza_xaccel_file_valido_nas_irraggiungibile(
            self, client, dati, nas_irraggiungibile, monkeypatch):
        """Percorso di fallback (use_xaccel=False): qui FastAPI apre
        davvero il file, quindi e' lei a dover rispondere in modo pulito
        se il NAS non e' raggiungibile."""
        from app.config import get_settings
        monkeypatch.setattr(get_settings(), "use_xaccel", False)
        media_id = dati["media_id"]
        r = client.get(f"/download/{media_id}")
        assert r.status_code in (404, 500)
        assert "Traceback" not in r.text
        if r.status_code == 500:
            assert "500" in r.text or "errore" in r.text.lower()


class TestVideoNasOffline:
    def test_video_xaccel_delega_a_nginx_senza_toccare_il_filesystem(
            self, client, nas_irraggiungibile):
        from app.database import get_db
        with get_db() as conn:
            riga = conn.execute(
                "SELECT m.id FROM media m JOIN nodes n ON n.id=m.node_id "
                "WHERE n.is_private=0 AND n.hidden=0 AND m.kind='video' LIMIT 1").fetchone()
        if not riga:
            pytest.skip("nessun video pubblico nel DB di test")
        r = client.get(f"/video/{riga['id']}")
        assert r.status_code == 200
        assert "x-accel-redirect" in {k.lower() for k in r.headers.keys()}
        assert "Traceback" not in r.text

    def test_video_senza_xaccel_file_valido_nas_irraggiungibile(
            self, client, nas_irraggiungibile, monkeypatch):
        from app.config import get_settings
        from app.database import get_db
        monkeypatch.setattr(get_settings(), "use_xaccel", False)
        with get_db() as conn:
            riga = conn.execute(
                "SELECT m.id FROM media m JOIN nodes n ON n.id=m.node_id "
                "WHERE n.is_private=0 AND n.hidden=0 AND m.kind='video' LIMIT 1").fetchone()
        if not riga:
            pytest.skip("nessun video pubblico nel DB di test")
        r = client.get(f"/video/{riga['id']}")
        assert r.status_code in (404, 500)
        assert "Traceback" not in r.text


class TestZipNasOffline:
    def test_zip_node_tutti_i_file_non_raggiungibili(self, client, dati, nas_irraggiungibile):
        node_id = dati["node_id"]
        assert node_id
        r = client.get(f"/zip/node/{node_id}")
        # Il filtro p.exists() a monte lascia la lista file vuota: 404
        # pulito, mai un archivio vuoto o un 500.
        assert r.status_code == 404
        assert "Traceback" not in r.text

    def test_zip_select_tutti_i_file_non_raggiungibili(self, client, dati, nas_irraggiungibile):
        media_id = dati["media_id"]
        assert media_id
        r = client.get(f"/zip/select?ids={media_id}")
        assert r.status_code in (403, 404)
        assert "Traceback" not in r.text


class TestShareSingolaNasOffline:
    """/f/{token}: serve un token reale. Se il DB di test non ne ha uno
    gia' generato per questa foto, lo si crea qui (stesso meccanismo di
    condividi()) invece di saltare il test — e' uno dei percorsi
    esplicitamente richiesti."""

    @pytest.fixture
    def token_pubblico(self, dati):
        from app.database import get_db
        from app.security import generate_access_token
        media_id = dati["media_id"]
        with get_db() as conn:
            row = conn.execute("SELECT share_token FROM media WHERE id=?",
                               (media_id,)).fetchone()
            if row and row["share_token"]:
                token = row["share_token"]
            else:
                token = generate_access_token()
                conn.execute("UPDATE media SET share_token=? WHERE id=?", (token, media_id))
                conn.commit()
        yield token

    def test_pagina_condivisa_file_non_raggiungibile(self, client, token_pubblico, nas_irraggiungibile):
        # La pagina HTML stessa non tocca il filesystem (solo i dati DB):
        # deve restare 200, il file mancante si vedra' sulle sotto-risorse.
        r = client.get(f"/f/{token_pubblico}")
        assert r.status_code == 200
        assert "Traceback" not in r.text

    def test_anteprima_condivisa_file_non_raggiungibile(self, client, token_pubblico, nas_irraggiungibile, dati):
        _pulisci_cache_per(dati["media_id"])
        r = client.get(f"/f/{token_pubblico}/anteprima")
        assert r.status_code == 404
        assert "Traceback" not in r.text

    def test_download_condiviso_xaccel_delega_a_nginx(self, client, token_pubblico, nas_irraggiungibile):
        r = client.get(f"/f/{token_pubblico}/download")
        assert r.status_code == 200
        assert "x-accel-redirect" in {k.lower() for k in r.headers.keys()}
        assert "Traceback" not in r.text

    def test_download_condiviso_senza_xaccel_file_non_raggiungibile(
            self, client, token_pubblico, nas_irraggiungibile, monkeypatch):
        from app.config import get_settings
        monkeypatch.setattr(get_settings(), "use_xaccel", False)
        r = client.get(f"/f/{token_pubblico}/download")
        assert r.status_code in (404, 500)
        assert "Traceback" not in r.text


class TestShareMultiplaNasOffline:
    """/fs/{token}: richiede una riga in condivisioni. La si crea qui con
    un insieme di media pubblici gia' esistenti (nessuna nuova struttura
    inventata, solo una riga di condivisione come la creerebbe un admin
    reale) e la si rimuove a fine test — questa e' l'unica scrittura del
    file, dichiarata ed esplicita, non un effetto collaterale del NAS
    offline."""

    @pytest.fixture
    def token_selezione(self, dati):
        from app.database import get_db
        from app.security import generate_access_token
        media_id = dati["media_id"]
        assert media_id
        token = generate_access_token()
        with get_db() as conn:
            conn.execute(
                "INSERT INTO condivisioni (token, media_ids, created_at) "
                "VALUES (?, ?, datetime('now'))", (token, str(media_id)))
            conn.commit()
        yield token
        with get_db() as conn:
            conn.execute("DELETE FROM condivisioni WHERE token=?", (token,))
            conn.commit()

    def test_pagina_selezione_file_non_raggiungibile(self, client, token_selezione, nas_irraggiungibile):
        r = client.get(f"/fs/{token_selezione}")
        assert r.status_code == 200
        assert "Traceback" not in r.text

    def test_miniatura_selezione_file_non_raggiungibile(self, client, token_selezione, nas_irraggiungibile, dati):
        _pulisci_cache_per(dati["media_id"])
        r = client.get(f"/fs/{token_selezione}/miniatura/{dati['media_id']}")
        assert r.status_code == 404
        assert "Traceback" not in r.text

    def test_zip_selezione_tutti_i_file_non_raggiungibili(self, client, token_selezione, nas_irraggiungibile):
        r = client.get(f"/fs/{token_selezione}/zip")
        assert r.status_code == 404
        assert "Traceback" not in r.text


class TestZipCadutaAMetaStreaming:
    """Il caso distinto da 'tutti i file assenti dall'inizio' (gia'
    coperto sopra da TestZipNasOffline con 404): qui il filtro .exists()
    iniziale accetta un file regolarmente presente, ma il file sparisce
    prima che zipstream riesca a leggerlo — la finestra di race che un
    NAS realmente instabile puo' aprire durante la compressione. Il punto
    che conta, come documentato nel commento di _RispostaZipConLucchetto,
    e' che il lucchetto si liberi comunque: altrimenti un solo download
    fallito per NAS instabile blocca quello stesso archivio per chiunque
    altro lo richieda dopo."""

    def test_lucchetto_si_libera_anche_se_un_file_sparisce_durante_lo_stream(
            self, client, tmp_path, monkeypatch):
        import shutil
        from app.config import get_settings
        from app.database import get_db
        from app.zip_lock import chiave_album, lucchetto_zip

        # Cerca direttamente un nodo pubblico con file diretti reali:
        # dati["node_id"] (fixture condivisa) puo' puntare a un album che
        # ha solo sottocartelle, senza foto proprie — qui serve un nodo
        # la cui rotta /zip/node prenda davvero il ramo "file diretti".
        with get_db() as conn:
            node_id = conn.execute(
                "SELECT n.id FROM nodes n JOIN media m ON m.node_id=n.id "
                "WHERE n.is_private=0 AND n.hidden=0 AND n.downloads_enabled=1 "
                "LIMIT 1").fetchone()
        if not node_id:
            pytest.skip("nessun nodo pubblico con file diretti nel DB di test")
        node_id = node_id["id"]
        with get_db() as conn:
            rows = conn.execute(
                "SELECT rel_path, filename FROM media WHERE node_id=? LIMIT 1",
                (node_id,)).fetchall()
        if not rows:
            pytest.skip("nodo di test senza file diretti")

        # Copia reale del primo file dell'album in una cartella locale
        # che imita photo_root: .exists() lo trova (supera il filtro
        # iniziale della rotta), ma lo si cancella subito prima che
        # zipstream tenti di leggerlo — e' la caduta a meta' del NAS.
        settings = get_settings()
        originale_root = settings.photo_root_path / rows[0]["rel_path"]
        if not originale_root.exists():
            pytest.skip("file sorgente non presente in questo ambiente")
        finto_root = tmp_path / "finto_nas"
        dest = finto_root / rows[0]["rel_path"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(originale_root, dest)
        monkeypatch.setattr(settings, "photo_root", str(finto_root))

        import app.routers.media as media_mod
        vero_zip_stream = media_mod._zip_stream

        def zip_stream_che_fa_sparire_il_file(files):
            # Il file sparisce (simula NAS caduto) subito dopo che la
            # rotta ha gia' superato il filtro .exists() e stringe il
            # lucchetto, ma prima che il contenuto venga davvero letto.
            for abs_path, _ in files:
                Path(abs_path).unlink(missing_ok=True)
            yield from vero_zip_stream(files)

        monkeypatch.setattr(media_mod, "_zip_stream", zip_stream_che_fa_sparire_il_file)

        k = chiave_album(node_id)
        r = client.get(f"/zip/node/{node_id}")
        # Qualunque sia il modo in cui lo streaming finisce (errore a
        # meta', risposta troncata), la parte che conta e' verificabile
        # subito dopo: il lucchetto non deve essere rimasto occupato.
        with lucchetto_zip(k):
            pass  # se non si fosse liberato, questo solleverebbe


class TestDbInvariato:
    """Controllo finale: nessuna delle richieste sopra deve aver alterato
    la struttura del database (nodes/media/condivisioni). I contatori di
    statistiche (record_stat/record_node_stat) non sono verificati qui:
    non sono struttura, e alcune rotte li scrivono anche in condizioni
    normali quando riescono a servire il file (es. con X-Accel-Redirect,
    che risponde 200 prima ancora che nginx verifichi il file) — non e'
    quello che questo task deve garantire."""

    def test_conteggi_invariati_dopo_lo_scenario_nas_offline(self, client, dati, nas_irraggiungibile):
        n_prima, m_prima, c_prima = _conteggi()
        client.get(f"/thumb/{dati['media_id']}")
        client.get(f"/download/{dati['media_id']}")
        client.get(f"/zip/node/{dati['node_id']}")
        n_dopo, m_dopo, c_dopo = _conteggi()
        assert (n_prima, m_prima, c_prima) == (n_dopo, m_dopo, c_dopo)
