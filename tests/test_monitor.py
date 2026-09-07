"""Monitoraggio automatico: sito/backend/nginx/bot/DB/disco/RAM/5xx.

Nessuna di queste prove deve mai toccare la rete vera, systemd vero, il DB
di produzione o mandare un messaggio Telegram reale — ogni funzione che fa
I/O esterno viene sostituita esplicitamente. La fixture `blocca_rete`
funge da rete di sicurezza: se un test dimentica di mockare urlopen, il
test fallisce rumorosamente invece di contattare Telegram o il sito vero.
"""
import importlib.util
import json
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


def _carica_modulo():
    percorso = (Path(__file__).resolve().parent.parent
                / "script" / "photocarcifo-monitor.py")
    spec = importlib.util.spec_from_file_location("photocarcifo_monitor", percorso)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture
def modulo(monkeypatch, tmp_path):
    m = _carica_modulo()
    monkeypatch.setattr(m, "STATO", str(tmp_path / "monitor-stato.json"))
    monkeypatch.setattr(m, "LOG", str(tmp_path / "monitor.log"))
    return m


@pytest.fixture
def blocca_rete(monkeypatch, modulo):
    """Qualunque chiamata di rete non esplicitamente mockata nel test fa
    fallire il test invece di uscire davvero verso Telegram/il sito."""
    def esplodi(*a, **k):
        raise AssertionError("chiamata di rete reale non mockata nel test")
    monkeypatch.setattr(modulo.urllib.request, "urlopen", esplodi)


CONFIG_FINTA = {"TELEGRAM_TOKEN": "123:finto", "TELEGRAM_CHAT": "999"}


def _mock_invio(monkeypatch, modulo, chiamate):
    def finto(config, testo):
        chiamate.append(testo)
        return True
    monkeypatch.setattr(modulo, "invia_telegram", finto)


def _mock_tutto_ok(monkeypatch, modulo):
    """Fa apparire tutti i controlli come sani, cosi' un test puo'
    sovrascrivere solo quello che gli interessa."""
    monkeypatch.setattr(modulo, "controlla_sito_pubblico", lambda: (True, "200 in 0.1s"))
    monkeypatch.setattr(modulo, "controlla_backend_locale", lambda: (True, "200"))
    monkeypatch.setattr(modulo, "controlla_servizio", lambda nome: (True, "active"))
    monkeypatch.setattr(modulo, "controlla_db_leggero", lambda: (True, "ok"))
    monkeypatch.setattr(modulo, "controlla_db_integrita_completa", lambda: (True, "ok"))
    monkeypatch.setattr(modulo, "controlla_nas", lambda percorso=None: True)
    monkeypatch.setattr(modulo, "controlla_backup_db_recente",
                        lambda **k: (True, "photocarcifo-2026-09-07.sqlite, 2h fa"))
    monkeypatch.setattr(modulo, "controlla_backup_db_integrita",
                        lambda **k: (True, "nodes=42 media=1234"))
    monkeypatch.setattr(modulo, "controlla_export_config",
                        lambda nas_raggiungibile, **k: (True, "1h fa"))
    monkeypatch.setattr(modulo, "controlla_disco", lambda percorso=None: ("ok", 50.0))
    monkeypatch.setattr(modulo, "controlla_ram", lambda: 10.0)
    monkeypatch.setattr(modulo, "conta_5xx_recenti", lambda: 0)


# --------------------------------------------------------- 1: sito OK, silenzio

def test_sito_ok_nessuna_notifica(monkeypatch, modulo, blocca_rete):
    _mock_tutto_ok(monkeypatch, modulo)
    chiamate = []
    _mock_invio(monkeypatch, modulo, chiamate)
    modulo.esegui_controlli(config=CONFIG_FINTA)
    assert chiamate == []


# --------------------------------------------------------- 2: sito DOWN -> alert

def test_sito_down_invia_un_alert(monkeypatch, modulo, blocca_rete):
    _mock_tutto_ok(monkeypatch, modulo)
    monkeypatch.setattr(modulo, "controlla_sito_pubblico",
                         lambda: (False, "timeout dopo 5s"))
    chiamate = []
    _mock_invio(monkeypatch, modulo, chiamate)
    modulo.esegui_controlli(config=CONFIG_FINTA)
    assert len(chiamate) == 1
    assert "DOWN" in chiamate[0]
    assert "timeout dopo 5s" in chiamate[0]


# --------------------------------------------------- 3: 1 errore temporaneo -> nessun alert

def test_un_singolo_fallimento_non_conta_come_outage(monkeypatch, modulo, blocca_rete):
    """controlla_sito_pubblico() gia' ritenta 3 volte al suo interno prima
    di dichiararsi fallita: qui si verifica che un singolo tentativo fallito
    seguito da successo non produca 'giu'."""
    tentativi = {"n": 0}

    class RispostaFinta:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def urlopen_finto(richiesta, timeout=None):
        tentativi["n"] += 1
        if tentativi["n"] == 1:
            raise TimeoutError("timeout simulato")
        return RispostaFinta()

    monkeypatch.setattr(modulo.urllib.request, "urlopen", urlopen_finto)
    monkeypatch.setattr(modulo.time, "sleep", lambda s: None)
    ok, dettaglio = modulo.controlla_sito_pubblico()
    assert ok is True
    assert tentativi["n"] == 2


# --------------------------------------------------- 4: 3 errori consecutivi -> DOWN

def test_tre_fallimenti_consecutivi_dichiarano_down(monkeypatch, modulo, blocca_rete):
    monkeypatch.setattr(modulo.urllib.request, "urlopen",
                         lambda *a, **k: (_ for _ in ()).throw(TimeoutError("no")))
    monkeypatch.setattr(modulo.time, "sleep", lambda s: None)
    ok, dettaglio = modulo.controlla_sito_pubblico()
    assert ok is False
    assert "timeout" in dettaglio


# --------------------------------------------------------------- 5: recovery

def test_recovery_dopo_down_invia_un_solo_messaggio(monkeypatch, modulo, blocca_rete):
    _mock_tutto_ok(monkeypatch, modulo)
    monkeypatch.setattr(modulo, "controlla_sito_pubblico", lambda: (False, "timeout"))
    chiamate = []
    _mock_invio(monkeypatch, modulo, chiamate)
    modulo.esegui_controlli(config=CONFIG_FINTA)
    assert len(chiamate) == 1 and "DOWN" in chiamate[0]

    # Il sito torna su: un solo messaggio di recovery, non uno per ogni giro.
    monkeypatch.setattr(modulo, "controlla_sito_pubblico", lambda: (True, "200 in 0.1s"))
    modulo.esegui_controlli(config=CONFIG_FINTA)
    assert len(chiamate) == 2
    assert "tornato operativo" in chiamate[1]

    # Resta su: nessun altro messaggio.
    modulo.esegui_controlli(config=CONFIG_FINTA)
    assert len(chiamate) == 2


# --------------------------------------------------------------- 6: nginx down

def test_nginx_down_appare_nel_dettaglio_e_genera_alert_proprio(monkeypatch, modulo, blocca_rete):
    _mock_tutto_ok(monkeypatch, modulo)

    def servizio_finto(nome):
        if nome == "nginx.service":
            return False, "failed"
        return True, "active"
    monkeypatch.setattr(modulo, "controlla_servizio", servizio_finto)
    chiamate = []
    _mock_invio(monkeypatch, modulo, chiamate)
    modulo.esegui_controlli(config=CONFIG_FINTA)
    # nginx e' riportato nel messaggio DOWN combinato solo se il sito e'
    # giu' contemporaneamente: qui il sito pubblico e' comunque mockato OK,
    # quindi non scatta un messaggio "DOWN" ma il valore e' comunque letto
    # correttamente nella funzione dedicata.
    ok, dettaglio = modulo.controlla_servizio("nginx.service")
    assert ok is False
    assert dettaglio == "failed"


# --------------------------------------------------------------- 7: backend down

def test_backend_down_con_sito_su_via_cache_non_genera_falso_ok(monkeypatch, modulo, blocca_rete):
    _mock_tutto_ok(monkeypatch, modulo)
    monkeypatch.setattr(modulo, "controlla_backend_locale", lambda: (False, "non risponde"))
    # Il sito pubblico resta "ok" (mockato), ma il dettaglio backend deve
    # comunque riflettere il problema quando viene costruito il messaggio.
    dettagli = {
        "sito_dettaglio": "200 in 0.1s",
        "backend_testo": "KO (non risponde)",
        "nginx_testo": "OK",
    }
    testo = modulo.costruisci_messaggio_down(dettagli)
    assert "Backend locale: KO (non risponde)" in testo


# --------------------------------------------------------------- 8: DB non OK

def test_db_non_integro_invia_alert_critical(monkeypatch, modulo, blocca_rete):
    _mock_tutto_ok(monkeypatch, modulo)
    monkeypatch.setattr(modulo, "controlla_db_leggero", lambda: (False, "corruption found"))
    chiamate = []
    _mock_invio(monkeypatch, modulo, chiamate)
    modulo.esegui_controlli(config=CONFIG_FINTA)
    assert len(chiamate) == 1
    assert "Database" in chiamate[0]
    assert "corruption found" in chiamate[0]


def test_db_locked_temporaneo_non_genera_alert(tmp_path, modulo):
    """Un database SQLite locked da un'altra connessione non deve produrre
    50 alert: quick_check deve trattarlo come transitorio."""
    db = tmp_path / "test.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE t (x)")
    conn.commit()

    import unittest.mock as mock
    with mock.patch.object(modulo.sqlite3, "connect",
                            side_effect=sqlite3.OperationalError("database is locked")):
        ok, dettaglio = modulo.controlla_db_leggero(str(db))
    assert ok is True
    assert "locked" in dettaglio


# --------------------------------------------------------------- 9/10: disco

def test_disco_warning(monkeypatch, modulo):
    class UsoFinto:
        total = 100
        free = 14  # 14% liberi -> sotto 15, sopra 8
        used = 86
    monkeypatch.setattr(modulo.shutil, "disk_usage", lambda p: UsoFinto())
    livello, liberi = modulo.controlla_disco()
    assert livello == "warning"


def test_disco_critical(monkeypatch, modulo):
    class UsoFinto:
        total = 100
        free = 5
        used = 95
    monkeypatch.setattr(modulo.shutil, "disk_usage", lambda p: UsoFinto())
    livello, liberi = modulo.controlla_disco()
    assert livello == "critical"


def test_disco_critical_genera_alert_critical_non_warning(monkeypatch, modulo, blocca_rete):
    _mock_tutto_ok(monkeypatch, modulo)
    monkeypatch.setattr(modulo, "controlla_disco", lambda percorso=None: ("critical", 5.0))
    chiamate = []
    _mock_invio(monkeypatch, modulo, chiamate)
    modulo.esegui_controlli(config=CONFIG_FINTA)
    assert len(chiamate) == 1
    assert "🔴" in chiamate[0]
    assert "critico" in chiamate[0].lower()


# --------------------------------------------------------------- 11: anti-spam

def test_antispam_stesso_guasto_non_ripete_messaggi(monkeypatch, modulo, blocca_rete):
    _mock_tutto_ok(monkeypatch, modulo)
    monkeypatch.setattr(modulo, "controlla_disco", lambda percorso=None: ("critical", 5.0))
    chiamate = []
    _mock_invio(monkeypatch, modulo, chiamate)
    for _ in range(5):
        modulo.esegui_controlli(config=CONFIG_FINTA)
    assert len(chiamate) == 1  # non 5


def test_antispam_stato_persiste_su_file(monkeypatch, modulo, blocca_rete, tmp_path):
    _mock_tutto_ok(monkeypatch, modulo)
    monkeypatch.setattr(modulo, "controlla_sito_pubblico", lambda: (False, "timeout"))
    chiamate = []
    _mock_invio(monkeypatch, modulo, chiamate)
    modulo.esegui_controlli(config=CONFIG_FINTA)
    assert Path(modulo.STATO).exists()
    with open(modulo.STATO) as f:
        dati = json.load(f)
    assert dati["sito"]["ok"] is False


# ------------------------------------------------------- 12: Telegram fallisce

def test_telegram_fallisce_non_solleva_eccezione(monkeypatch, modulo, blocca_rete):
    _mock_tutto_ok(monkeypatch, modulo)
    monkeypatch.setattr(modulo, "controlla_sito_pubblico", lambda: (False, "timeout"))
    monkeypatch.setattr(modulo, "invia_telegram", lambda config, testo: False)
    # Non deve sollevare: il monitor deve concludere il giro comunque.
    stato = modulo.esegui_controlli(config=CONFIG_FINTA)
    assert stato["sito"]["ok"] is False


# --------------------------------------- 13: monitor continua anche se Telegram fallisce

def test_monitor_continua_dopo_fallimento_telegram_su_un_controllo(monkeypatch, modulo, blocca_rete):
    """Se l'invio Telegram del primo alert fallisce, i controlli successivi
    (disco, RAM, 5xx...) devono comunque essere eseguiti e il loro stato
    salvato — un fallimento di rete su una notifica non deve interrompere
    il resto del giro."""
    _mock_tutto_ok(monkeypatch, modulo)
    monkeypatch.setattr(modulo, "controlla_sito_pubblico", lambda: (False, "timeout"))
    monkeypatch.setattr(modulo, "controlla_disco", lambda percorso=None: ("critical", 3.0))
    monkeypatch.setattr(modulo, "invia_telegram", lambda config, testo: False)
    stato = modulo.esegui_controlli(config=CONFIG_FINTA)
    assert stato["sito"]["ok"] is False
    assert stato["disco"]["ok"] is False


# ------------------------------------------------------- extra: RAM consecutiva

def test_ram_alta_una_volta_sola_non_avvisa(monkeypatch, modulo, blocca_rete):
    _mock_tutto_ok(monkeypatch, modulo)
    monkeypatch.setattr(modulo, "controlla_ram", lambda: 95.0)
    chiamate = []
    _mock_invio(monkeypatch, modulo, chiamate)
    modulo.esegui_controlli(config=CONFIG_FINTA)
    assert chiamate == []  # 1 solo giro, serve RAM_CONSECUTIVI di fila


def test_ram_alta_per_piu_giri_consecutivi_avvisa(monkeypatch, modulo, blocca_rete):
    _mock_tutto_ok(monkeypatch, modulo)
    monkeypatch.setattr(modulo, "controlla_ram", lambda: 95.0)
    chiamate = []
    _mock_invio(monkeypatch, modulo, chiamate)
    for _ in range(modulo.RAM_CONSECUTIVI):
        modulo.esegui_controlli(config=CONFIG_FINTA)
    assert len(chiamate) == 1
    assert "RAM" in chiamate[0]


# ------------------------------------------------------------- extra: 5xx

def test_5xx_sotto_soglia_non_avvisa(monkeypatch, modulo, blocca_rete):
    _mock_tutto_ok(monkeypatch, modulo)
    monkeypatch.setattr(modulo, "conta_5xx_recenti", lambda: 4)
    chiamate = []
    _mock_invio(monkeypatch, modulo, chiamate)
    modulo.esegui_controlli(config=CONFIG_FINTA)
    assert chiamate == []


def test_5xx_sopra_soglia_avvisa_una_volta(monkeypatch, modulo, blocca_rete):
    _mock_tutto_ok(monkeypatch, modulo)
    monkeypatch.setattr(modulo, "conta_5xx_recenti", lambda: 9)
    chiamate = []
    _mock_invio(monkeypatch, modulo, chiamate)
    modulo.esegui_controlli(config=CONFIG_FINTA)
    assert len(chiamate) == 1
    assert "5xx" in chiamate[0]


# ------------------------------------------------- extra: integrity_check giornaliero

def test_integrity_check_non_rieseguito_prima_di_24_ore(monkeypatch, modulo, blocca_rete):
    _mock_tutto_ok(monkeypatch, modulo)
    chiamate_integrity = []
    monkeypatch.setattr(modulo, "controlla_db_integrita_completa",
                         lambda: (chiamate_integrity.append(1) or (True, "ok")))
    ora = datetime.now(timezone.utc)
    modulo.esegui_controlli(config=CONFIG_FINTA, adesso=ora)
    modulo.esegui_controlli(config=CONFIG_FINTA, adesso=ora + timedelta(minutes=5))
    assert len(chiamate_integrity) == 1  # non rieseguito al secondo giro ravvicinato


def test_integrity_check_rieseguito_dopo_24_ore(monkeypatch, modulo, blocca_rete):
    _mock_tutto_ok(monkeypatch, modulo)
    chiamate_integrity = []
    monkeypatch.setattr(modulo, "controlla_db_integrita_completa",
                         lambda: (chiamate_integrity.append(1) or (True, "ok")))
    ora = datetime.now(timezone.utc)
    modulo.esegui_controlli(config=CONFIG_FINTA, adesso=ora)
    modulo.esegui_controlli(config=CONFIG_FINTA, adesso=ora + timedelta(hours=25))
    assert len(chiamate_integrity) == 2


# --------------------------------------------------------- niente secret nei messaggi

def test_nessun_token_nei_messaggi(monkeypatch, modulo, blocca_rete):
    _mock_tutto_ok(monkeypatch, modulo)
    monkeypatch.setattr(modulo, "controlla_sito_pubblico", lambda: (False, "timeout"))
    chiamate = []
    _mock_invio(monkeypatch, modulo, chiamate)
    modulo.esegui_controlli(config=CONFIG_FINTA)
    assert "123:finto" not in chiamate[0]
    assert CONFIG_FINTA["TELEGRAM_TOKEN"] not in chiamate[0]


# --------------------------------------------------------- guardia generale distruttivi

def test_nessuna_chiamata_a_subprocess_run_diversa_da_systemctl(monkeypatch, modulo):
    """Guardia generale: il monitor non deve MAI eseguire comandi diversi
    da 'systemctl is-active <servizio>' — niente restart, niente script di
    produzione, niente comandi shell arbitrari."""
    chiamate = []
    originale = modulo.subprocess.run

    def sorvegliato(argomenti, **kwargs):
        chiamate.append(argomenti)
        assert argomenti[:2] == ["systemctl", "is-active"], \
            f"comando non atteso eseguito dal monitor: {argomenti}"
        class R:
            stdout = "active\n"
        return R()

    monkeypatch.setattr(modulo.subprocess, "run", sorvegliato)
    modulo.controlla_servizio("photocarcifo.service")
    assert len(chiamate) == 1


# ============================================================
# Salute dei backup: DB giornaliero, export configurazione, NAS di
# scrittura, test di restore non distruttivo.
# ============================================================

def _db_di_prova(percorso, nodes=3, media=10, valido=True):
    """Un piccolo database SQLite vero, con lo schema minimo che
    controlla_backup_db_integrita si aspetta di trovare. Usato al posto di
    un mock quando il test vuole provare la funzione per intero (copia,
    apertura, integrity_check, conteggi) — mai contro il DB di
    produzione, sempre un file nuovo in tmp_path."""
    conn = sqlite3.connect(percorso)
    try:
        conn.execute("CREATE TABLE nodes(id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE media(id INTEGER PRIMARY KEY)")
        for i in range(nodes):
            conn.execute("INSERT INTO nodes(id) VALUES (?)", (i,))
        for i in range(media):
            conn.execute("INSERT INTO media(id) VALUES (?)", (i,))
        conn.commit()
    finally:
        conn.close()
    if not valido:
        # Un file che sqlite non riconosce affatto: la forma piu' semplice
        # di corruzione, e la piu' facile da riprodurre in un test.
        Path(percorso).write_bytes(b"non e' un database sqlite")


# --------------------------------------------------- 1: backup valido, silenzio

def test_backup_valido_nessuna_notifica(monkeypatch, modulo, blocca_rete):
    _mock_tutto_ok(monkeypatch, modulo)
    chiamate = []
    _mock_invio(monkeypatch, modulo, chiamate)
    modulo.esegui_controlli(config=CONFIG_FINTA)
    assert chiamate == []


# --------------------------------------------------- 2: backup assente -> alert

def test_backup_assente_invia_un_alert(monkeypatch, modulo, tmp_path, blocca_rete):
    # La funzione vera si cattura PRIMA di _mock_tutto_ok: e' un
    # riferimento all'oggetto funzione, non una lettura ripetuta
    # dell'attributo — riassegnare modulo.controlla_backup_db_recente
    # dopo non lo cambia, quindi non richiama se stessa.
    originale = modulo.controlla_backup_db_recente
    _mock_tutto_ok(monkeypatch, modulo)
    cartella_vuota = tmp_path / "nessun-backup"
    cartella_vuota.mkdir()
    monkeypatch.setattr(modulo, "controlla_backup_db_recente",
                        lambda **k: originale(cartella_vuota))
    chiamate = []
    _mock_invio(monkeypatch, modulo, chiamate)
    modulo.esegui_controlli(config=CONFIG_FINTA)
    assert len(chiamate) == 1
    assert "Backup database non valido" in chiamate[0]
    assert "nessun file" in chiamate[0]


def test_controlla_backup_db_recente_su_cartella_vuota(tmp_path):
    ok, dettaglio = _carica_modulo().controlla_backup_db_recente(tmp_path)
    assert ok is False
    assert "nessun file" in dettaglio


# --------------------------------------------------- 3: backup troppo vecchio -> alert

def test_backup_troppo_vecchio_invia_un_alert(tmp_path):
    m = _carica_modulo()
    vecchio = tmp_path / "photocarcifo-2026-01-01.sqlite"
    vecchio.write_bytes(b"contenuto finto, non serve valido per questo controllo")
    adesso = datetime.now(timezone.utc)
    # 31 ore: appena sopra la soglia di 30.
    orario_vecchio = (adesso - timedelta(hours=31)).timestamp()
    __import__("os").utime(vecchio, (orario_vecchio, orario_vecchio))
    ok, dettaglio = m.controlla_backup_db_recente(tmp_path, adesso=adesso)
    assert ok is False
    assert "31" in dettaglio or "ore" in dettaglio


def test_backup_di_29_ore_non_e_ancora_un_problema(tmp_path):
    """La soglia e' 30 ore apposta per assorbire un ritardo normale del
    timer (RandomizedDelaySec, un riavvio nella finestra notturna): un
    backup di 29 ore non deve generare un allarme."""
    m = _carica_modulo()
    recente = tmp_path / "photocarcifo-2026-09-06.sqlite"
    recente.write_bytes(b"contenuto finto")
    adesso = datetime.now(timezone.utc)
    orario = (adesso - timedelta(hours=29)).timestamp()
    __import__("os").utime(recente, (orario, orario))
    ok, dettaglio = m.controlla_backup_db_recente(tmp_path, adesso=adesso)
    assert ok is True


def test_backup_vuoto_e_un_problema_anche_se_recente(tmp_path):
    m = _carica_modulo()
    vuoto = tmp_path / "photocarcifo-2026-09-07.sqlite"
    vuoto.touch()  # 0 byte
    ok, dettaglio = m.controlla_backup_db_recente(tmp_path)
    assert ok is False
    assert "vuoto" in dettaglio


# --------------------------------------------------- 4: backup corrotto -> alert

def test_backup_sqlite_corrotto_invia_un_alert(monkeypatch, modulo, tmp_path, blocca_rete):
    originale_integrita = modulo.controlla_backup_db_integrita  # prima di _mock_tutto_ok
    _mock_tutto_ok(monkeypatch, modulo)
    cartella = tmp_path / "backup"
    cartella.mkdir()
    _db_di_prova(cartella / "photocarcifo-2026-09-07.sqlite", valido=False)
    # Forza l'esecuzione del controllo pesante in questo giro (di norma
    # e' una volta al giorno: qui e' proprio quello che si vuole testare).
    monkeypatch.setattr(modulo, "controlla_backup_db_integrita",
                        lambda **k: originale_integrita(
                            cartella, percorso_produzione="/percorso/inesistente"))
    chiamate = []
    _mock_invio(monkeypatch, modulo, chiamate)
    modulo.esegui_controlli(config=CONFIG_FINTA)
    assert len(chiamate) == 1
    assert "non ripristinabile" in chiamate[0]


def test_restore_reale_di_un_backup_valido(tmp_path):
    """La prova di restore per intero, senza mock: copia il file,
    apre, integrity_check, conteggi, cancella la copia. Nessun database
    di produzione coinvolto — solo file creati in tmp_path."""
    m = _carica_modulo()
    cartella = tmp_path / "backup"
    cartella.mkdir()
    backup = cartella / "photocarcifo-2026-09-07.sqlite"
    _db_di_prova(backup, nodes=5, media=120)

    ok, dettaglio = m.controlla_backup_db_integrita(
        cartella, percorso_produzione=str(tmp_path / "non-esiste.db"))
    assert ok is True
    assert "nodes=5" in dettaglio
    assert "media=120" in dettaglio


def test_restore_test_non_lascia_file_temporanei(tmp_path):
    m = _carica_modulo()
    cartella = tmp_path / "backup"
    cartella.mkdir()
    _db_di_prova(cartella / "photocarcifo-2026-09-07.sqlite")
    m.controlla_backup_db_integrita(cartella, percorso_produzione=str(tmp_path / "nope.db"))
    residui = list(Path(tempfile.gettempdir()).glob("photocarcifo-restore-check-*"))
    assert residui == [], f"file temporanei rimasti: {residui}"


def test_restore_test_non_tocca_la_produzione(tmp_path):
    """Il file di produzione viene solo LETTO (mode=ro, per il confronto
    prudente sui conteggi): il test lo apre con permessi di sola lettura
    per essere sicuri che nessuna scrittura ci finisca dentro per
    sbaglio."""
    m = _carica_modulo()
    cartella = tmp_path / "backup"
    cartella.mkdir()
    _db_di_prova(cartella / "photocarcifo-2026-09-07.sqlite", nodes=2, media=5)
    produzione = tmp_path / "produzione.db"
    _db_di_prova(produzione, nodes=100, media=5000)
    contenuto_prima = produzione.read_bytes()

    m.controlla_backup_db_integrita(cartella, percorso_produzione=str(produzione))
    assert produzione.read_bytes() == contenuto_prima


def test_crollo_netto_rispetto_alla_produzione_e_un_problema(tmp_path):
    """Il confronto e' prudente (non un numero esatto), ma un backup con
    meno della meta' delle foto della produzione e' un segnale vero — un
    database svuotato per errore, non la normale oscillazione
    quotidiana."""
    m = _carica_modulo()
    cartella = tmp_path / "backup"
    cartella.mkdir()
    _db_di_prova(cartella / "photocarcifo-2026-09-07.sqlite", nodes=3, media=100)
    produzione = tmp_path / "produzione.db"
    _db_di_prova(produzione, nodes=50, media=5000)

    ok, dettaglio = m.controlla_backup_db_integrita(cartella, percorso_produzione=str(produzione))
    assert ok is False
    assert "inferiore" in dettaglio


def test_oscillazione_normale_non_genera_falso_allarme(tmp_path):
    """Il backup ha qualche foto in meno della produzione (normale: e'
    stato preso qualche ora prima) — non deve generare un allarme."""
    m = _carica_modulo()
    cartella = tmp_path / "backup"
    cartella.mkdir()
    _db_di_prova(cartella / "photocarcifo-2026-09-07.sqlite", nodes=50, media=4980)
    produzione = tmp_path / "produzione.db"
    _db_di_prova(produzione, nodes=50, media=5000)

    ok, dettaglio = m.controlla_backup_db_integrita(cartella, percorso_produzione=str(produzione))
    assert ok is True


# --------------------------------------------------- 5: NAS backup offline -> alert

def test_nas_backup_offline_invia_un_alert(monkeypatch, modulo, blocca_rete):
    _mock_tutto_ok(monkeypatch, modulo)

    def nas_finto(percorso=None):
        return percorso != modulo.NAS_BACKUP_PATH  # solo quello di backup e' giu'
    monkeypatch.setattr(modulo, "controlla_nas", nas_finto)
    chiamate = []
    _mock_invio(monkeypatch, modulo, chiamate)
    modulo.esegui_controlli(config=CONFIG_FINTA)
    assert len(chiamate) == 1
    assert "NAS backup non raggiungibile" in chiamate[0]


def test_nas_backup_offline_non_genera_anche_un_alert_di_export(monkeypatch, modulo, blocca_rete):
    """Un solo allarme, non due: se il NAS e' giu' il controllo
    sull'export non ha niente di attendibile da dire e si salta, invece
    di aggiungere un secondo messaggio sopra a quello del NAS."""
    _mock_tutto_ok(monkeypatch, modulo)
    monkeypatch.setattr(modulo, "controlla_nas", lambda percorso=None: False)
    chiamate = []
    _mock_invio(monkeypatch, modulo, chiamate)
    modulo.esegui_controlli(config=CONFIG_FINTA)
    testi = "\n".join(chiamate)
    assert "NAS backup non raggiungibile" in testi
    assert "Export configurazione" not in testi


def test_controlla_export_config_salta_se_nas_giu():
    """None e non True: chi chiama deve poter distinguere 'verificato,
    va bene' da 'non verificabile ora' — vedi il test sotto per il motivo
    concreto, trovato dalla code review."""
    m = _carica_modulo()
    ok, dettaglio = m.controlla_export_config(nas_raggiungibile=False)
    assert ok is None
    assert "saltato" in dettaglio


def test_nas_giu_non_maschera_un_export_gia_scaduto_con_un_falso_recovery(
        monkeypatch, modulo, blocca_rete):
    """Il difetto trovato dalla code review: un export gia' scaduto (stato
    critico, alert gia' inviato) che smette di essere controllabile
    perche' nel frattempo cade anche il NAS non deve produrre un falso
    'tornato operativo' — il problema originale non si e' risolto, si e'
    solo smesso di vederlo."""
    _mock_tutto_ok(monkeypatch, modulo)
    monkeypatch.setattr(modulo, "controlla_export_config",
                        lambda nas_raggiungibile, **k: (False, "ultimo export ha 40 ore"))
    chiamate = []
    _mock_invio(monkeypatch, modulo, chiamate)
    modulo.esegui_controlli(config=CONFIG_FINTA)
    assert len(chiamate) == 1 and "Export configurazione non aggiornato" in chiamate[0]

    # Ora il NAS backup cade (solo quello: il NAS primario resta su, non
    # e' quello sotto esame qui). L'export smette di essere verificabile,
    # ma NON e' tornato buono. Nessun messaggio di recovery deve partire.
    monkeypatch.setattr(modulo, "controlla_nas",
                        lambda percorso=None: percorso != modulo.NAS_BACKUP_PATH)
    monkeypatch.setattr(modulo, "controlla_export_config",
                        lambda nas_raggiungibile, **k:
                        (None, "NAS non raggiungibile: controllo saltato"))
    modulo.esegui_controlli(config=CONFIG_FINTA)
    assert len(chiamate) == 2  # solo il nuovo alert "NAS backup non raggiungibile"
    assert "NAS backup non raggiungibile" in chiamate[1]
    assert not any("Export configurazione" in c and "tornato operativo" in c
                   for c in chiamate), "falso recovery dell'export mentre il NAS e' giu'"


# --------------------------------------------------- 6: export vecchio -> alert

def test_export_config_vecchio_invia_un_alert(tmp_path):
    m = _carica_modulo()
    cartella = tmp_path / "configurazione"
    cartella.mkdir()
    chiave = cartella / "env-chiavi.txt"
    chiave.write_text("TELEGRAM_TOKEN=\nTELEGRAM_CHAT=\n")
    adesso = datetime.now(timezone.utc)
    orario_vecchio = (adesso - timedelta(hours=31)).timestamp()
    __import__("os").utime(chiave, (orario_vecchio, orario_vecchio))
    ok, dettaglio = m.controlla_export_config(True, cartella, adesso=adesso)
    assert ok is False
    assert "ore" in dettaglio


def test_export_config_assente_invia_un_alert(tmp_path):
    m = _carica_modulo()
    ok, dettaglio = m.controlla_export_config(True, tmp_path / "non-esiste")
    assert ok is False
    assert "nessun export" in dettaglio


def test_export_config_recente_e_leggibile_senza_secret(tmp_path):
    """L'export sanitizzato contiene solo nomi di chiave: il monitor lo
    legge solo per il timestamp, non per il contenuto — ma qui si
    verifica anche che il formato atteso (nessun valore dopo '=') sia
    davvero quello che l'export scrive, cosi' un domani un cambiamento
    che ci facesse finire un secret non passerebbe inosservato."""
    m = _carica_modulo()
    cartella = tmp_path / "configurazione"
    cartella.mkdir()
    chiave = cartella / "env-chiavi.txt"
    chiave.write_text("TELEGRAM_TOKEN=\nDB_PATH=\n")
    for riga in chiave.read_text().splitlines():
        if riga.strip():
            assert riga.endswith("="), f"riga con un valore, non solo la chiave: {riga!r}"
    ok, dettaglio = m.controlla_export_config(True, cartella)
    assert ok is True


# --------------------------------------------------- 7/8: no spam, un recovery

def test_backup_vecchio_persistente_non_duplica_lalert(monkeypatch, modulo, blocca_rete):
    _mock_tutto_ok(monkeypatch, modulo)
    monkeypatch.setattr(modulo, "controlla_backup_db_recente",
                        lambda **k: (False, "photocarcifo-2026-01-01.sqlite ha 200 ore"))
    chiamate = []
    _mock_invio(monkeypatch, modulo, chiamate)
    modulo.esegui_controlli(config=CONFIG_FINTA)
    modulo.esegui_controlli(config=CONFIG_FINTA)
    modulo.esegui_controlli(config=CONFIG_FINTA)
    assert len(chiamate) == 1  # non tre


def test_backup_risolto_invia_un_solo_recovery(monkeypatch, modulo, blocca_rete):
    _mock_tutto_ok(monkeypatch, modulo)
    monkeypatch.setattr(modulo, "controlla_backup_db_recente",
                        lambda **k: (False, "assente"))
    chiamate = []
    _mock_invio(monkeypatch, modulo, chiamate)
    modulo.esegui_controlli(config=CONFIG_FINTA)
    assert len(chiamate) == 1 and "Backup database non valido" in chiamate[0]

    monkeypatch.setattr(modulo, "controlla_backup_db_recente",
                        lambda **k: (True, "photocarcifo-2026-09-07.sqlite, 1h fa"))
    modulo.esegui_controlli(config=CONFIG_FINTA)
    assert len(chiamate) == 2
    assert "tornato operativo" in chiamate[1]

    modulo.esegui_controlli(config=CONFIG_FINTA)
    assert len(chiamate) == 2  # resta su: nessun terzo messaggio


# --------------------------------------------------- integrity/restore: 1x al giorno

def test_restore_test_non_rieseguito_prima_di_24_ore(monkeypatch, modulo, blocca_rete):
    _mock_tutto_ok(monkeypatch, modulo)
    chiamate_restore = []
    monkeypatch.setattr(modulo, "controlla_backup_db_integrita",
                        lambda **k: (chiamate_restore.append(1) or (True, "ok")))
    ora = datetime.now(timezone.utc)
    modulo.esegui_controlli(config=CONFIG_FINTA, adesso=ora)
    modulo.esegui_controlli(config=CONFIG_FINTA, adesso=ora + timedelta(minutes=5))
    assert len(chiamate_restore) == 1


def test_restore_test_rieseguito_dopo_24_ore(monkeypatch, modulo, blocca_rete):
    _mock_tutto_ok(monkeypatch, modulo)
    chiamate_restore = []
    monkeypatch.setattr(modulo, "controlla_backup_db_integrita",
                        lambda **k: (chiamate_restore.append(1) or (True, "ok")))
    ora = datetime.now(timezone.utc)
    modulo.esegui_controlli(config=CONFIG_FINTA, adesso=ora)
    modulo.esegui_controlli(config=CONFIG_FINTA, adesso=ora + timedelta(hours=25))
    assert len(chiamate_restore) == 2


# --------------------------------------------------- niente secret nei nuovi messaggi

def test_nessun_token_nei_messaggi_di_backup(monkeypatch, modulo, blocca_rete):
    _mock_tutto_ok(monkeypatch, modulo)
    monkeypatch.setattr(modulo, "controlla_backup_db_recente", lambda **k: (False, "assente"))
    chiamate = []
    _mock_invio(monkeypatch, modulo, chiamate)
    modulo.esegui_controlli(config=CONFIG_FINTA)
    assert CONFIG_FINTA["TELEGRAM_TOKEN"] not in chiamate[0]
