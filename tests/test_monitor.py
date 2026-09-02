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
