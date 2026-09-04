"""Controlli sul progetto nel suo insieme, non sulle singole pagine.

Sono le cose che non si rompono oggi ma il giorno in cui si reinstalla, e
allora e' tardi: una libreria usata e mai dichiarata, un'impostazione che
il file di esempio non nomina, un file di configurazione con dentro un
segreto vero.
"""
import re
import sys
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent

ALIAS = {  # nome con cui si importa -> nome del pacchetto da installare
    "pil": "pillow",
    "argon2": "argon2-cffi",
    "zipstream": "zipstream-new",
    "pydantic_settings": "pydantic-settings",
    "rapidocr_onnxruntime": "rapidocr-onnxruntime",
}


def _librerie_usate() -> set:
    interne = {"app"} | {p.stem for p in (RADICE / "app").rglob("*.py")}
    trovate = set()
    for f in (RADICE / "app").rglob("*.py"):
        for m in re.finditer(r"^\s*(?:from|import)\s+([a-zA-Z_]\w*)",
                             f.read_text(encoding="utf-8"), re.M):
            nome = m.group(1)
            if nome not in sys.stdlib_module_names and nome not in interne \
                    and not nome.startswith("_"):
                trovate.add(nome)
    return trovate


def _librerie_dichiarate() -> set:
    dichiarate = set()
    for nome in ("requirements.txt", "requirements-ocr.txt"):
        for riga in (RADICE / nome).read_text(encoding="utf-8").splitlines():
            riga = riga.split("#")[0].strip()
            if riga:
                dichiarate.add(re.split(r"[=<>\[]", riga)[0].strip().lower())
    return dichiarate


def test_ogni_libreria_usata_e_dichiarata():
    """Il 17/08/2026 il file delle librerie non nominava pyotp, qrcode e
    zipstream: una reinstallazione da zero sarebbe partita senza verifica
    in due passaggi e senza scaricamento degli album, e il guasto si
    sarebbe visto solo usando quelle due cose."""
    dichiarate = _librerie_dichiarate()
    mancanti = sorted(n for n in _librerie_usate()
                      if ALIAS.get(n.lower(), n.lower()) not in dichiarate)
    assert not mancanti, (
        f"usate nel codice ma non in requirements: {mancanti}. "
        "Da qui il sito funziona (sono installate), ma reinstallandolo no.")


def test_il_file_di_esempio_nomina_tutte_le_impostazioni():
    """Chi rimonta il sito parte da .env.example: se non nomina
    un'impostazione, quella prende il valore predefinito in silenzio."""
    esempio = (RADICE / ".env.example").read_text(encoding="utf-8")
    nominate = set(re.findall(r"^\s*#?\s*([A-Z][A-Z0-9_]+)\s*=", esempio, re.M))
    from app.config import Settings
    attese = {c.upper() for c in Settings.model_fields}
    # secret_key e' l'unica che il file di esempio non deve contenere gia'
    # pronta: va generata da chi installa.
    mancanti = sorted(attese - nominate)
    assert not mancanti, f"impostazioni non documentate in .env.example: {mancanti}"


def test_nessun_segreto_vero_nel_file_di_esempio():
    esempio = (RADICE / ".env.example").read_text(encoding="utf-8")
    for riga in esempio.splitlines():
        if riga.strip().startswith("SECRET_KEY="):
            valore = riga.split("=", 1)[1].strip()
            assert len(valore) < 32 or not re.fullmatch(r"[0-9a-f]{32,}", valore), \
                "il file di esempio contiene una chiave che sembra vera"


def test_il_file_con_i_segreti_non_e_leggibile_da_tutti():
    env = RADICE / ".env"
    if not env.exists():
        return
    modo = env.stat().st_mode & 0o777
    assert modo & 0o077 == 0, (
        f".env ha permessi {oct(modo)}: lo puo' leggere anche chi non deve")


def test_il_file_con_i_segreti_appartiene_al_servizio():
    """Il 01/09/2026 .env e' finito di proprieta' di root invece che
    dell'utente photocarcifo (vedi deploy/photocarcifo.service, User=
    Group=photocarcifo): il servizio non riusciva piu' a leggerlo e il sito
    e' rimasto giu' fino al riavvio successivo. photocarcifo-applica.sh
    ora corregge questo da solo prima di riavviare (vedi il passo "I
    permessi di .env"); qui si verifica che l'ambiente corrente sia gia'
    nello stato giusto, non solo che lo script sappia sistemarlo."""
    import pwd
    env = RADICE / ".env"
    if not env.exists():
        return
    try:
        atteso = pwd.getpwnam("photocarcifo")
    except KeyError:
        return  # ambiente senza quell'utente (es. sviluppo locale): salta
    proprietario = env.stat().st_uid
    assert proprietario == atteso.pw_uid, (
        f".env appartiene a uid {proprietario}, non a photocarcifo (uid {atteso.pw_uid})")


def test_niente_segreti_scritti_nel_codice():
    sospetti = []
    schema = re.compile(
        r"""(password|secret|token|api_?key)\s*=\s*["']([^"']{12,})["']""", re.I)
    for f in (RADICE / "app").rglob("*.py"):
        for n, riga in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            m = schema.search(riga)
            if not m:
                continue
            valore = m.group(2)
            # I nomi di campo, i percorsi e i testi non sono segreti.
            if valore.startswith(("/", "http", "{")) or " " in valore:
                continue
            sospetti.append(f"{f.name}:{n}")
    assert not sospetti, f"possibili segreti scritti nel codice: {sospetti}"


def test_il_database_ha_gli_indici_che_le_pagine_usano():
    """Senza un indice la pagina funziona lo stesso, solo lentamente: e' il
    tipo di peggioramento che non si nota finche' l'archivio non cresce."""
    from app.database import get_db
    attesi = {"idx_media_node", "idx_numeri_numero", "idx_numeri_media",
              "idx_nodes_parent", "idx_nodes_token", "idx_nodes_data"}
    with get_db() as conn:
        presenti = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'").fetchall()}
    mancanti = sorted(attesi - presenti)
    assert not mancanti, f"indici mancanti: {mancanti}"


def test_il_database_e_integro():
    from app.database import get_db
    with get_db() as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def _blocco_permessi_env(script_testo: str) -> str:
    """Estrae solo il passo 'I permessi di .env' da photocarcifo-applica.sh,
    dall'intestazione del passo fino alla riga vuota prima del passo
    successivo: i test qui sotto verificano quella logica isolata, senza
    eseguire l'intero script (che riavvierebbe nginx/systemd davvero)."""
    inizio = script_testo.index('passo "I permessi di .env"')
    fine = script_testo.index('\nif [ "$SOLO_PROVA" = 1 ]', inizio)
    return script_testo[inizio:fine]


def test_lo_script_di_deploy_non_tocca_env_in_modalita_prova(tmp_path):
    """Il 01/09/2026 un salvataggio di .env lo ha lasciato di proprieta' di
    root: il servizio (utente photocarcifo) non riusciva piu' a leggerlo e
    il sito e' rimasto giu' al riavvio successivo. Qui si verifica che
    photocarcifo-applica.sh --prova, di fronte a permessi sbagliati,
    ABORTISCA e non modifichi il file (--prova promette di non toccare
    nulla) — e che invece la modalita' normale corregga owner e permessi
    prima del riavvio, cosi' l'incidente non puo' ripetersi."""
    import subprocess

    import os
    import pwd
    try:
        pwd.getpwnam("photocarcifo")
    except KeyError:
        return  # ambiente senza quell'utente: il controllo non si applica

    # pytest crea tmp_path con permessi 700: nessuno tranne root potrebbe
    # attraversarla, il che farebbe fallire "su photocarcifo -c test -r"
    # per un motivo estraneo al test (la cartella, non il file). In
    # produzione la working directory e' /opt/photocarcifo, attraversabile
    # da tutti — qui si replica quella condizione, non se ne introduce
    # una nuova.
    os.chmod(tmp_path, 0o755)

    script = (RADICE / "script" / "photocarcifo-applica.sh").read_text(encoding="utf-8")
    blocco = _blocco_permessi_env(script)

    finto = tmp_path / ".env"
    finto.write_text("SECRET_KEY=test\n", encoding="utf-8")
    os.chown(finto, 0, 0)  # root:root, come nell'incidente reale
    finto.chmod(0o600)

    copione = f"""#!/bin/bash
set -uo pipefail
cd {tmp_path}
SOLO_PROVA=1
passo() {{ printf '\\n▸ %s\\n' "$1"; }}
ko() {{ printf '  x %s\\n' "$1"; exit 1; }}
ok() {{ printf '  ok %s\\n' "$1"; }}
{blocco}
"""
    eseguibile = tmp_path / "prova.sh"
    eseguibile.write_text(copione, encoding="utf-8")
    eseguibile.chmod(0o755)

    r = subprocess.run(["bash", str(eseguibile)], capture_output=True, text=True)
    assert r.returncode != 0, "con permessi sbagliati --prova doveva abortire, non proseguire"
    assert finto.stat().st_uid == 0, "--prova non deve MAI modificare .env, nemmeno per correggerlo"

    # Ora la modalita' normale (SOLO_PROVA=0): deve correggere da sola.
    copione_vero = copione.replace("SOLO_PROVA=1", "SOLO_PROVA=0")
    eseguibile.write_text(copione_vero, encoding="utf-8")
    r2 = subprocess.run(["bash", str(eseguibile)], capture_output=True, text=True)
    assert r2.returncode == 0, f"il deploy vero doveva correggere da solo: {r2.stdout}{r2.stderr}"
    atteso = pwd.getpwnam("photocarcifo")
    assert finto.stat().st_uid == atteso.pw_uid, "il deploy vero non ha corretto l'owner di .env"
    assert (finto.stat().st_mode & 0o777) == 0o600, "il deploy vero non ha corretto i permessi di .env"


def test_scanner_stesso_stato_due_scansioni_zero_notifiche_indexnow(tmp_path, monkeypatch):
    """Un restart (applicazione o CT) non deve mai far ripartire lo scanner
    come se ogni album fosse nuovo: lo stato 'e' gia' pubblico' vive nel
    database su disco (nodes.total_media/is_private/hidden), non in
    memoria, quindi sopravvive a qualunque riavvio. Qui si verifica che
    due scansioni consecutive sullo STESSO stato del NAS producano
    entrambe zero notifiche IndexNow — non solo la seconda: nemmeno la
    prima, se il DB arriva gia' con lo stato di un giro precedente."""
    import sqlite3
    import contextlib

    monkeypatch.setenv("SITE_URL", "https://photocarcifo.ch")
    monkeypatch.setenv("INDEXNOW_KEY", "")  # non deve nemmeno provare a mandare nulla
    from app.config import get_settings
    get_settings.cache_clear()

    nas = tmp_path / "nas"
    (nas / "CATEGORIA" / "Album").mkdir(parents=True)

    from PIL import Image
    Image.new("RGB", (10, 10)).save(nas / "CATEGORIA" / "Album" / "foto1.jpg")

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
    import app.scanner as scanner_mod
    monkeypatch.setattr(database_mod, "get_db", get_db_isolato)
    monkeypatch.setattr(scanner_mod, "get_db", get_db_isolato)
    # tmp_path e' una cartella locale, non un vero mount NFS: senza
    # questo, _nas_disponibile() la rifiuterebbe a ragione (e' proprio
    # il caso che protegge in produzione). Qui si simula solo che il
    # NAS sia raggiungibile, non si aggira il controllo altrove.
    vero_ismount = scanner_mod.os.path.ismount
    monkeypatch.setattr(
        scanner_mod.os.path, "ismount",
        lambda p: True if str(p) == str(nas) else vero_ismount(p))

    database_mod.init_db()

    s = scanner_mod.Scanner(full=False)
    s.root = nas
    r1 = s.run()
    assert r1["nodes_added"] >= 1, "il primo giro deve aver trovato l'album (precondizione del test)"

    # Secondo giro, stesso identico stato del NAS: nessuna modifica.
    s2 = scanner_mod.Scanner(full=False)
    s2.root = nas
    s2.run()
    assert s2._slug_da_notificare == set(), (
        f"secondo scan sullo stesso stato ha comunque notificato: {s2._slug_da_notificare}")

    # Un "restart" e' esattamente questo: un nuovo processo Scanner, che
    # rilegge lo stato dal disco invece che tenerlo in memoria.
    s3 = scanner_mod.Scanner(full=False)
    s3.root = nas
    s3.run()
    assert s3._slug_da_notificare == set(), (
        f"scan dopo un 'restart' simulato ha rinotificato album gia' noti: {s3._slug_da_notificare}")


def _scanner_isolato(tmp_path, monkeypatch):
    """Stesso setup di test_scanner_stesso_stato_due_scansioni_zero_notifiche_indexnow:
    Scanner reale su un NAS finto in tmp_path, DB isolato su file temporaneo."""
    import sqlite3
    import contextlib

    monkeypatch.setenv("SITE_URL", "https://photocarcifo.ch")
    monkeypatch.setenv("INDEXNOW_KEY", "")
    from app.config import get_settings
    get_settings.cache_clear()

    nas = tmp_path / "nas"
    nas.mkdir()
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
    import app.scanner as scanner_mod
    monkeypatch.setattr(database_mod, "get_db", get_db_isolato)
    monkeypatch.setattr(scanner_mod, "get_db", get_db_isolato)
    vero_ismount = scanner_mod.os.path.ismount
    monkeypatch.setattr(
        scanner_mod.os.path, "ismount",
        lambda p: True if str(p) == str(nas) else vero_ismount(p))

    database_mod.init_db()
    return nas, scanner_mod


def _conta_nodi(dbfile):
    import sqlite3
    conn = sqlite3.connect(str(dbfile))
    n = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    conn.close()
    return n


def test_cartella_vuota_transitoria_conta_come_aggiunta_e_rimossa(tmp_path, monkeypatch):
    """Una cartella vista dal filesystem, creata come nodo e subito scartata
    (vuota, non configurata) nello stesso ciclo di scan: e' un evento di
    aggiunta E un evento di rimozione avvenuti entrambi durante questo scan,
    anche se il DB finale non cambia. Prima del fix, nodes_removed restava a
    0 nonostante il DELETE fosse eseguito davvero (vedi app/scanner.py, il
    DELETE per "subtotal == 0 and not configurato")."""
    nas, scanner_mod = _scanner_isolato(tmp_path, monkeypatch)
    (nas / "CartellaVuota").mkdir()

    s = scanner_mod.Scanner(full=False)
    s.root = nas
    esito = s.run()

    assert esito["nodes_added"] == 1
    assert esito["nodes_removed"] == 1
    dbfile = tmp_path / "photocarcifo.db"
    assert _conta_nodi(dbfile) == 0, "il nodo transitorio non deve restare nel DB"


def test_album_reale_con_media_incrementa_solo_nodes_added(tmp_path, monkeypatch):
    """Un album con una fotografia vera resta nel DB: aggiunto, mai
    rimosso."""
    nas, scanner_mod = _scanner_isolato(tmp_path, monkeypatch)
    (nas / "CATEGORIA" / "Album").mkdir(parents=True)
    from PIL import Image
    Image.new("RGB", (10, 10)).save(nas / "CATEGORIA" / "Album" / "foto1.jpg")

    s = scanner_mod.Scanner(full=False)
    s.root = nas
    esito = s.run()

    assert esito["nodes_added"] == 2  # CATEGORIA + Album
    assert esito["nodes_removed"] == 0
    dbfile = tmp_path / "photocarcifo.db"
    assert _conta_nodi(dbfile) == 2


def test_nodo_esistente_sparito_dal_nas_incrementa_nodes_removed(tmp_path, monkeypatch):
    """Il percorso di rimozione gia' esistente (nodo persistito in un giro
    precedente, poi sparito davvero dal NAS) deve continuare a funzionare
    come prima: non e' quello toccato dal fix."""
    nas, scanner_mod = _scanner_isolato(tmp_path, monkeypatch)
    (nas / "CATEGORIA" / "Album").mkdir(parents=True)
    from PIL import Image
    Image.new("RGB", (10, 10)).save(nas / "CATEGORIA" / "Album" / "foto1.jpg")

    s = scanner_mod.Scanner(full=False)
    s.root = nas
    r1 = s.run()
    assert r1["nodes_added"] == 2

    # La cartella Album (con la foto) sparisce davvero dal NAS.
    import shutil
    shutil.rmtree(nas / "CATEGORIA" / "Album")

    s2 = scanner_mod.Scanner(full=False)
    s2.root = nas
    r2 = s2.run()

    assert r2["nodes_removed"] >= 1
    dbfile = tmp_path / "photocarcifo.db"
    assert _conta_nodi(dbfile) == 0
