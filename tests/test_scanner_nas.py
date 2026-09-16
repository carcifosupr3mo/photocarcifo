"""Un NAS offline non deve mai poter essere scambiato per un NAS vuoto:
lo scanner deve fermarsi PRIMA di toccare nodes/media, non dopo aver
gia' interpretato l'assenza come "tutto rimosso". Vedi PROJECT_KNOWLEDGE.md,
sezione Scanner, per il contesto del bug che questi test coprono.
"""
import os
import sqlite3
import tempfile
from pathlib import Path

from app.config import get_settings
from app.scanner import Scanner, _nas_disponibile


def _conteggi():
    conn = sqlite3.connect(str(get_settings().db_path))
    n = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    m = conn.execute("SELECT COUNT(*) FROM media").fetchone()[0]
    conn.close()
    return n, m


def test_nas_disponibile_su_mount_reale():
    # /mnt/magazzino e' il mount NFS reale del server di test: se questo
    # fallisse in CI significherebbe che il mount non e' configurato li',
    # non che la funzione sia sbagliata — skip esplicito in quel caso.
    root = get_settings().photo_root_path
    if not root.exists():
        import pytest
        pytest.skip("PHOTO_ROOT non presente in questo ambiente")
    assert _nas_disponibile(root) is True


def test_nas_disponibile_path_inesistente():
    assert _nas_disponibile(Path("/tmp/percorso-che-non-esiste-mai-xyz")) is False


def test_nas_disponibile_directory_locale_vuota_non_e_un_mount():
    """Il caso critico: una cartella locale che esiste ed e' vuota (come
    apparirebbe un mountpoint NFS staccato) non deve mai risultare
    disponibile solo perche' .exists() e' vero."""
    with tempfile.TemporaryDirectory() as tmp:
        vuota = Path(tmp)
        assert vuota.exists() is True
        assert os.path.ismount(vuota) is False
        assert _nas_disponibile(vuota) is False


def test_nas_disponibile_directory_illeggibile():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        os.chmod(d, 0o000)
        try:
            assert _nas_disponibile(d) is False
        finally:
            os.chmod(d, 0o755)


def test_scan_con_root_non_montata_non_tocca_il_database():
    """Prova end-to-end: uno scan reale (non un mock) puntato su una
    directory locale vuota deve abortire subito, senza cancellare nulla."""
    n_prima, m_prima = _conteggi()
    with tempfile.TemporaryDirectory() as tmp:
        s = Scanner()
        s.root = Path(tmp)
        esito = s.run()
    n_dopo, m_dopo = _conteggi()
    assert n_prima == n_dopo
    assert m_prima == m_dopo
    assert esito["nodes_removed"] == 0
    assert esito["media_removed"] == 0


def test_scan_ciclo_orfani_non_cancella_se_nas_sparisce_a_meta(monkeypatch):
    """Il gap trovato dalla code review: il NAS e' disponibile al
    controllo iniziale di run() (lo supera) ma sparisce subito dopo,
    mentre il ciclo di pulizia nodi orfani e' in corso — quello che
    cancella nodes confrontando rel_path con il filesystem reale. Un
    nodo fittizio con un rel_path inesistente forza deterministicamente
    il primo giro del ciclo a vedere "assente", cosi' il test non
    dipende da un disallineamento gia' presente per caso nel DB reale.
    A quel punto lo scan deve fermarsi, non scambiare la caduta per
    "tutto rimosso" e proseguire a cancellare anche il resto."""
    import app.scanner as scanner_mod

    root = scanner_mod.get_settings().photo_root_path
    if not root.exists():
        import pytest
        pytest.skip("PHOTO_ROOT non presente in questo ambiente")

    conn = sqlite3.connect(str(get_settings().db_path))
    cur = conn.execute(
        "INSERT INTO nodes (rel_path, slug, name, title, total_media, is_private, hidden, "
        "created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 0, 0, 0, datetime('now'), datetime('now'))",
        ("__nodo-fittizio-per-test-nas-xyz__", "nodo-fittizio-per-test-nas-xyz",
         "Nodo fittizio test", "Nodo fittizio test"))
    id_fittizio = cur.lastrowid
    conn.commit()
    conn.close()

    n_prima, m_prima = _conteggi()

    chiamate = {"n": 0}

    def ismount_vero_la_prima_poi_falso(path):
        chiamate["n"] += 1
        # 1a chiamata: il controllo iniziale in run() — lo lascia
        # passare, cosi' il ciclo orfani parte davvero e arriva a
        # valutare il nodo fittizio (che e' certamente "assente").
        return chiamate["n"] <= 1

    monkeypatch.setattr(scanner_mod.os.path, "ismount", ismount_vero_la_prima_poi_falso)
    try:
        s = Scanner()
        s.root = root
        esito = s.run()

        n_dopo, m_dopo = _conteggi()
        # Il punto centrale: il nodo fittizio e' certamente assente dal
        # filesystem, ma la caduta simulata del NAS deve impedire che
        # venga cancellato — e deve impedire che il ciclo prosegua a
        # cancellare qualunque altro nodo scambiando la caduta per una
        # rimozione reale.
        assert n_dopo == n_prima
        assert m_dopo == m_prima
        assert esito["nodes_removed"] == 0
        assert chiamate["n"] >= 2
    finally:
        conn = sqlite3.connect(str(get_settings().db_path))
        conn.execute("DELETE FROM nodes WHERE id=?", (id_fittizio,))
        conn.commit()
        conn.close()
