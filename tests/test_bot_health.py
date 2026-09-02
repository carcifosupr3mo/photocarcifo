"""Il comando Telegram /health (script/photocarcifo-bot.py:cmd_health).

/health non rilancia mai il monitor: legge solo l'ultimo stato che il
timer photocarcifo-monitor.timer scrive ogni 5 minuti in
/var/lib/photocarcifo/monitor-stato.json. Qui il modulo del monitor viene
sostituito con un finto (_ModuloMonitorFinto) che restituisce uno stato
costruito a mano — stesso pattern gia' usato per _modulo_ban_alert() in
test_bot_bloccati.py — cosi' il test non tocca mai ne' il monitor vero
ne' la rete ne' systemctl.
"""
from datetime import datetime, timedelta, timezone

import pytest

from test_bot_telegram import _carica_modulo  # riusa il loader esistente


class _ModuloMonitorFinto:
    """Sostituisce _modulo_monitor(): stesse costanti del modulo vero
    (servono a cmd_health per niente in realta', dato che le soglie sono
    gia' state applicate a monte nel dict 'dettagli_ultimo' salvato dal
    monitor — qui si simula solo leggi_stato())."""
    def __init__(self, stato):
        self._stato = stato

    def leggi_stato(self):
        if self._stato is None:
            raise OSError("file non leggibile")
        return self._stato


def _stato_ok(minuti_fa=2):
    quando = (datetime.now(timezone.utc) - timedelta(minutes=minuti_fa))
    return {
        "ultimo_check": quando.isoformat(timespec="seconds"),
        "dettagli_ultimo": {
            "sito_ok": True, "sito_dettaglio": "200 in 0.1s",
            "backend_ok": True, "backend_dettaglio": "200",
            "nginx_ok": True, "nginx_dettaglio": "active",
            "app_ok": True, "bot_ok": True,
            "db_ok": True, "db_dettaglio": "ok",
            "db_integrity_quando": quando.isoformat(timespec="seconds"),
            "db_integrity_ok": True,
            "disco_livello": "ok", "disco_liberi_pct": 59.0,
            "ram_pct": 18.0, "ram_ok": True,
            "quanti_5xx": 0, "5xx_ok": True,
        },
    }


@pytest.fixture
def bot_health(monkeypatch, tmp_path):
    modulo = _carica_modulo()

    chiamate = []

    def tg_finta(metodo, attesa=20, **dati):
        chiamate.append({"metodo": metodo, "dati": dati})
        return {"ok": True, "result": [] if metodo == "getUpdates" else True}

    monkeypatch.setattr(modulo, "tg", tg_finta)
    monkeypatch.setattr(modulo, "LOG", str(tmp_path / "bot.log"))
    monkeypatch.setattr(modulo, "attivo", lambda servizio: True)
    modulo._CHIAMATE = chiamate
    modulo._attesa.clear()
    modulo._in_corso = None
    modulo._ULTIMO_RESPINTO.clear()
    return modulo


# ------------------------------------------------------------ 1: tutto OK

def test_tutto_ok_stato_operativo(bot_health, monkeypatch):
    monkeypatch.setattr(bot_health, "_modulo_monitor",
                         lambda: _ModuloMonitorFinto(_stato_ok()))
    r = bot_health.cmd_health()
    assert "🟢" in r
    assert "OPERATIVO" in r
    assert "HTTPS: ✅" in r
    assert "59% libero" in r
    assert "18%" in r


# ------------------------------------------------------------ 2: sito down

def test_sito_down_stato_critical(bot_health, monkeypatch):
    s = _stato_ok()
    s["dettagli_ultimo"]["sito_ok"] = False
    s["dettagli_ultimo"]["sito_dettaglio"] = "timeout dopo 5s"
    monkeypatch.setattr(bot_health, "_modulo_monitor", lambda: _ModuloMonitorFinto(s))
    r = bot_health.cmd_health()
    assert "🔴" in r
    assert "CRITICAL" in r
    assert "HTTPS: ❌ timeout dopo 5s" in r


# ------------------------------------------------------------ 3: backend down

def test_backend_down_stato_almeno_warning(bot_health, monkeypatch):
    s = _stato_ok()
    s["dettagli_ultimo"]["backend_ok"] = False
    s["dettagli_ultimo"]["backend_dettaglio"] = "non risponde"
    monkeypatch.setattr(bot_health, "_modulo_monitor", lambda: _ModuloMonitorFinto(s))
    r = bot_health.cmd_health()
    assert "Backend: ❌ non risponde" in r
    assert "🟡" in r or "🔴" in r
    assert "OPERATIVO" not in r


# ------------------------------------------------------------ 4: nginx down

def test_nginx_down_mostrato_chiaramente(bot_health, monkeypatch):
    s = _stato_ok()
    s["dettagli_ultimo"]["nginx_ok"] = False
    s["dettagli_ultimo"]["nginx_dettaglio"] = "failed"
    monkeypatch.setattr(bot_health, "_modulo_monitor", lambda: _ModuloMonitorFinto(s))
    r = bot_health.cmd_health()
    assert "Nginx: ❌ failed" in r


# ------------------------------------------------------------ 5: DB down

def test_db_down_stato_critical(bot_health, monkeypatch):
    s = _stato_ok()
    s["dettagli_ultimo"]["db_ok"] = False
    s["dettagli_ultimo"]["db_dettaglio"] = "corruption found"
    monkeypatch.setattr(bot_health, "_modulo_monitor", lambda: _ModuloMonitorFinto(s))
    r = bot_health.cmd_health()
    assert "🔴" in r
    assert "DB: ❌ corruption found" in r


# ------------------------------------------------------------ 6: disco warning

def test_disco_warning(bot_health, monkeypatch):
    s = _stato_ok()
    s["dettagli_ultimo"]["disco_livello"] = "warning"
    s["dettagli_ultimo"]["disco_liberi_pct"] = 13.0
    monkeypatch.setattr(bot_health, "_modulo_monitor", lambda: _ModuloMonitorFinto(s))
    r = bot_health.cmd_health()
    assert "Disco: ⚠️ 13% libero" in r
    assert "🟡" in r


# ------------------------------------------------------------ 7: disco critical

def test_disco_critical(bot_health, monkeypatch):
    s = _stato_ok()
    s["dettagli_ultimo"]["disco_livello"] = "critical"
    s["dettagli_ultimo"]["disco_liberi_pct"] = 6.0
    monkeypatch.setattr(bot_health, "_modulo_monitor", lambda: _ModuloMonitorFinto(s))
    r = bot_health.cmd_health()
    assert "Disco: 🔴 6% libero" in r
    assert "🔴" in r
    assert "CRITICAL" in r


# ------------------------------------------------------------ 8: RAM warning

def test_ram_warning(bot_health, monkeypatch):
    s = _stato_ok()
    s["dettagli_ultimo"]["ram_ok"] = False
    s["dettagli_ultimo"]["ram_pct"] = 93.0
    monkeypatch.setattr(bot_health, "_modulo_monitor", lambda: _ModuloMonitorFinto(s))
    r = bot_health.cmd_health()
    assert "RAM: ⚠️ 93%" in r


# ------------------------------------------------------------ 9: 5xx warning

def test_5xx_warning(bot_health, monkeypatch):
    s = _stato_ok()
    s["dettagli_ultimo"]["5xx_ok"] = False
    s["dettagli_ultimo"]["quanti_5xx"] = 9
    monkeypatch.setattr(bot_health, "_modulo_monitor", lambda: _ModuloMonitorFinto(s))
    r = bot_health.cmd_health()
    assert "5xx: ⚠️ 9" in r


# ------------------------------------------------- extra: integrity mai girato in sessione

def test_integrity_sconosciuta_non_mostrata_come_fallita(bot_health, monkeypatch):
    """L'integrity_check completo gira una volta al giorno: se in questo
    avvio del monitor non e' ancora girato, db_integrity_ok e' None (non
    ancora misurato), non False — /health deve distinguere i due casi
    invece di mostrare un falso ❌ per un controllo mai eseguito."""
    s = _stato_ok()
    s["dettagli_ultimo"]["db_integrity_ok"] = None
    monkeypatch.setattr(bot_health, "_modulo_monitor", lambda: _ModuloMonitorFinto(s))
    r = bot_health.cmd_health()
    assert "Integrity: ❓" in r
    assert "Integrity: ❌" not in r


# ------------------------------------------------------------ 10: file assente

def test_file_stato_assente_non_crasha(bot_health, monkeypatch):
    monkeypatch.setattr(bot_health, "_modulo_monitor", lambda: _ModuloMonitorFinto({}))
    r = bot_health.cmd_health()
    assert "non disponibile" in r
    assert "sconosciuto" in r


# ------------------------------------------------------------ 11: file corrotto

def test_file_stato_corrotto_non_crasha(bot_health, monkeypatch):
    monkeypatch.setattr(bot_health, "_modulo_monitor", lambda: _ModuloMonitorFinto(None))
    r = bot_health.cmd_health()
    assert "non disponibile" in r


# ------------------------------------------------------------ 12: stato vecchio >10 min

def test_stato_vecchio_oltre_10_min_avvisa(bot_health, monkeypatch):
    s = _stato_ok(minuti_fa=15)
    monkeypatch.setattr(bot_health, "_modulo_monitor", lambda: _ModuloMonitorFinto(s))
    r = bot_health.cmd_health()
    assert "non aggiornato" in r


# ------------------------------------------------------------ 13: stato molto vecchio >20 min

def test_stato_molto_vecchio_oltre_20_min_critical(bot_health, monkeypatch):
    s = _stato_ok(minuti_fa=25)
    monkeypatch.setattr(bot_health, "_modulo_monitor", lambda: _ModuloMonitorFinto(s))
    r = bot_health.cmd_health()
    assert "probabilmente fermo" in r
    assert "🔴" in r
    assert "CRITICAL" in r


# ------------------------------------------------------------ 14: timer monitor inattivo

def test_timer_monitor_inattivo_mostrato(bot_health, monkeypatch):
    monkeypatch.setattr(bot_health, "_modulo_monitor", lambda: _ModuloMonitorFinto(_stato_ok()))
    monkeypatch.setattr(bot_health, "attivo", lambda servizio: False)
    r = bot_health.cmd_health()
    assert "Monitor: 🔴 timer fermo" in r


# ------------------------------------------------------------ 15: utente non autorizzato
#
# Copertura reale (non solo lettura del sorgente): "health" e' stato
# aggiunto alla lista parametrizzata di test_estraneo_prova_ogni_comando_
# nessuno_funziona in test_bot_telegram_sicurezza.py, che simula un
# estraneo (chat_id diverso da quello autorizzato) e verifica che nessuna
# risposta parta e nessuna chiamata a tg() avvenga per QUEL comando
# specifico — stesso giro completo (autorizzato() + gestisci()) di tutti
# gli altri, nessun percorso separato per /health.


# ------------------------------------------------------------ 16: /health nel menu

def test_health_presente_nel_menu_setmycommands(bot_health):
    import inspect
    sorgente = inspect.getsource(bot_health.main)
    inizio = sorgente.index("for c, d in [", sorgente.index('tg("setMyCommands"'))
    blocco = sorgente[inizio:sorgente.index("]))", inizio)]
    assert '"health"' in blocco
    assert "health" in bot_health.COMANDI


# ------------------------------------------------------------ 17/18/19/20: nessuna azione reale

def test_health_e_read_only_nessuna_chiamata_esegui(bot_health, monkeypatch):
    """/health non deve mai chiamare esegui() (che lancia subprocess reali
    come script di produzione/restart): solo leggi_stato() e attivo()
    (systemctl is-active, gia' mockato sopra a livello di fixture)."""
    chiamate_esegui = []
    monkeypatch.setattr(bot_health, "esegui", lambda *a, **k: chiamate_esegui.append(a) or "")
    monkeypatch.setattr(bot_health, "_modulo_monitor", lambda: _ModuloMonitorFinto(_stato_ok()))
    bot_health.cmd_health()
    assert chiamate_esegui == []


def test_health_zero_chiamate_telegram_reali(bot_health, monkeypatch):
    monkeypatch.setattr(bot_health, "_modulo_monitor", lambda: _ModuloMonitorFinto(_stato_ok()))
    bot_health.cmd_health()
    # tg() e' gia' sostituita dalla fixture: qui si verifica solo che
    # cmd_health() non l'abbia chiamata affatto (non manda messaggi da
    # solo, il testo torna al chiamante che lo invia).
    assert bot_health._CHIAMATE == []


def test_health_non_modifica_stato_del_monitor(bot_health, monkeypatch, tmp_path):
    """cmd_health non deve mai scrivere/sovrascrivere il file di stato del
    monitor: solo leggi_stato(), mai scrivi_stato()."""
    finto = _ModuloMonitorFinto(_stato_ok())
    scritture = []
    finto.scrivi_stato = lambda s: scritture.append(s)
    monkeypatch.setattr(bot_health, "_modulo_monitor", lambda: finto)
    bot_health.cmd_health()
    assert scritture == []


def test_health_gestito_da_gestisci_come_gli_altri_comandi(bot_health, monkeypatch):
    monkeypatch.setattr(bot_health, "_modulo_monitor", lambda: _ModuloMonitorFinto(_stato_ok()))
    r = bot_health.gestisci("/health")
    assert "PhotoCarcifo HEALTH" in r
