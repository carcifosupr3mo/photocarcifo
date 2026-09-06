"""Test mirati: visibilita' pubblica degli album collegati ai raduni.

Un album puo' essere collegato in anticipo a un raduno (raduni_albums) prima
di avere fotografie. La relazione resta sempre presente; cio' che cambia e'
solo se l'album compare in _album_pubblici() (usata da /radunimoto), in base
al conteggio reale dei media (total_media, lo stesso usato ovunque nel sito).
_album_admin() (pannello) non applica questo filtro: l'admin vede sempre
tutti gli album collegati, vuoti o no.

DB isolato su file temporaneo (stesso pattern di
tests/test_progetto.py::_scanner_isolato): nessuna scrittura sul DB vero.
"""
import sqlite3
import contextlib


def _db_isolato(tmp_path, monkeypatch):
    from app.config import get_settings
    get_settings.cache_clear()

    dbfile = tmp_path / "photocarcifo.db"

    @contextlib.contextmanager
    def get_db_isolato():
        conn = sqlite3.connect(str(dbfile))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    from app import database as database_mod
    import app.routers.raduni as raduni_mod
    monkeypatch.setattr(database_mod, "get_db", get_db_isolato)
    monkeypatch.setattr(raduni_mod, "get_db", get_db_isolato)
    database_mod.init_db()
    return dbfile, raduni_mod


def _crea_raduno(dbfile):
    conn = sqlite3.connect(str(dbfile))
    cur = conn.execute(
        "INSERT INTO raduni (data, luogo, creato) "
        "VALUES (date('now', '+7 days'), 'Manno', datetime('now'))")
    raduno_id = cur.lastrowid
    conn.commit()
    conn.close()
    return raduno_id


def _crea_album(dbfile, slug, *, is_private=0, hidden=0, total_media=0,
                 expires_at=None):
    conn = sqlite3.connect(str(dbfile))
    cur = conn.execute(
        "INSERT INTO nodes (slug, rel_path, name, title, is_private, hidden, "
        "total_media, direct_media, expires_at, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
        (slug, slug, slug, slug, is_private, hidden, total_media,
         total_media, expires_at))
    node_id = cur.lastrowid
    conn.commit()
    conn.close()
    return node_id


def _collega(dbfile, raduno_id, node_id):
    conn = sqlite3.connect(str(dbfile))
    conn.execute(
        "INSERT INTO raduni_albums (raduno_id, node_id, creato) "
        "VALUES (?, ?, datetime('now'))", (raduno_id, node_id))
    conn.commit()
    conn.close()


def _imposta_media(dbfile, node_id, totale):
    conn = sqlite3.connect(str(dbfile))
    conn.execute("UPDATE nodes SET total_media=?, direct_media=? WHERE id=?",
                 (totale, totale, node_id))
    conn.commit()
    conn.close()


def _relazione_presente(dbfile, raduno_id, node_id):
    conn = sqlite3.connect(str(dbfile))
    r = conn.execute(
        "SELECT 1 FROM raduni_albums WHERE raduno_id=? AND node_id=?",
        (raduno_id, node_id)).fetchone()
    conn.close()
    return r is not None


# --- TEST 1: album vuoto collegato -----------------------------------------

def test_album_vuoto_collegato_visibile_solo_in_admin(tmp_path, monkeypatch):
    dbfile, raduni_mod = _db_isolato(tmp_path, monkeypatch)
    raduno_id = _crea_raduno(dbfile)
    node_id = _crea_album(dbfile, "raduno-xyz-vuoto", total_media=0)
    _collega(dbfile, raduno_id, node_id)

    admin = raduni_mod._album_admin(raduno_id)
    pubblici = raduni_mod._album_pubblici(raduno_id)

    assert [a["id"] for a in admin] == [node_id]
    assert pubblici == []
    assert _relazione_presente(dbfile, raduno_id, node_id)


# --- TEST 2: aggiunta prima foto --------------------------------------------

def test_prima_foto_rende_visibile_pubblicamente(tmp_path, monkeypatch):
    dbfile, raduni_mod = _db_isolato(tmp_path, monkeypatch)
    raduno_id = _crea_raduno(dbfile)
    node_id = _crea_album(dbfile, "raduno-xyz-prima-foto", total_media=0)
    _collega(dbfile, raduno_id, node_id)
    assert raduni_mod._album_pubblici(raduno_id) == []

    # Lo scanner aggiorna total_media dopo aver trovato foto: nessuna
    # modifica a raduni_albums, nessuna azione nel sistema Raduni.
    _imposta_media(dbfile, node_id, 12)

    pubblici = raduni_mod._album_pubblici(raduno_id)
    assert [a["id"] for a in pubblici] == [node_id]
    assert pubblici[0]["total_media"] == 12
    assert _relazione_presente(dbfile, raduno_id, node_id)


# --- TEST 3: ritorno a zero --------------------------------------------------

def test_media_rimossi_torna_non_visibile_ma_resta_collegato(tmp_path, monkeypatch):
    dbfile, raduni_mod = _db_isolato(tmp_path, monkeypatch)
    raduno_id = _crea_raduno(dbfile)
    node_id = _crea_album(dbfile, "raduno-xyz-svuotato", total_media=5)
    _collega(dbfile, raduno_id, node_id)
    assert len(raduni_mod._album_pubblici(raduno_id)) == 1

    _imposta_media(dbfile, node_id, 0)

    assert raduni_mod._album_pubblici(raduno_id) == []
    admin = raduni_mod._album_admin(raduno_id)
    assert [a["id"] for a in admin] == [node_id]
    assert _relazione_presente(dbfile, raduno_id, node_id)


# --- TEST 4: privacy ha sempre precedenza -----------------------------------

def test_album_privato_con_foto_non_appare_pubblicamente(tmp_path, monkeypatch):
    dbfile, raduni_mod = _db_isolato(tmp_path, monkeypatch)
    raduno_id = _crea_raduno(dbfile)
    node_id = _crea_album(dbfile, "raduno-xyz-privato", is_private=1, total_media=8)
    _collega(dbfile, raduno_id, node_id)
    assert raduni_mod._album_pubblici(raduno_id) == []


def test_album_nascosto_con_foto_non_appare_pubblicamente(tmp_path, monkeypatch):
    dbfile, raduni_mod = _db_isolato(tmp_path, monkeypatch)
    raduno_id = _crea_raduno(dbfile)
    node_id = _crea_album(dbfile, "raduno-xyz-nascosto", hidden=1, total_media=8)
    _collega(dbfile, raduno_id, node_id)
    assert raduni_mod._album_pubblici(raduno_id) == []


def test_album_scaduto_con_foto_non_appare_pubblicamente(tmp_path, monkeypatch):
    dbfile, raduni_mod = _db_isolato(tmp_path, monkeypatch)
    raduno_id = _crea_raduno(dbfile)
    node_id = _crea_album(dbfile, "raduno-xyz-scaduto", total_media=8,
                          expires_at="2000-01-01")
    _collega(dbfile, raduno_id, node_id)
    assert raduni_mod._album_pubblici(raduno_id) == []


# --- TEST 5: subtree (conteggio aggregato) ----------------------------------

def test_album_con_foto_solo_in_sottocartella_appare(tmp_path, monkeypatch):
    """Un padre con 0 foto dirette ma una sottocartella con foto: nella
    semantica reale del progetto (scanner._walk) total_media del padre e'
    gia' il conteggio aggregato del subtree, non solo direct_media. Qui si
    simula direttamente il risultato che lo scanner avrebbe scritto."""
    dbfile, raduni_mod = _db_isolato(tmp_path, monkeypatch)
    raduno_id = _crea_raduno(dbfile)
    padre_id = _crea_album(dbfile, "raduno-xyz-padre", total_media=0)
    _collega(dbfile, raduno_id, padre_id)
    assert raduni_mod._album_pubblici(raduno_id) == []

    # Una sottocartella riceve foto; lo scanner ricalcola total_media del
    # padre come somma ricorsiva (vedi scanner.py:_walk), qui riprodotta.
    _crea_album(dbfile, "raduno-xyz-padre/sotto", total_media=3)
    _imposta_media(dbfile, padre_id, 3)

    pubblici = raduni_mod._album_pubblici(raduno_id)
    assert [a["id"] for a in pubblici] == [padre_id]
    assert pubblici[0]["total_media"] == 3
