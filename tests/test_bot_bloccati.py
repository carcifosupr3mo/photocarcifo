"""/bloccati con dettagli del ban (script/photocarcifo-bot.py).

Il comando legge lo storico salvato da photocarcifo-ban-alert.py al
momento del ban (salva_snapshot/leggi_snapshot) — MAI un nuovo lookup
GeoIP/AbuseIPDB qui, verificato esplicitamente intercettando
urllib.request.urlopen. `esegui()` (che chiamerebbe fail2ban-client
davvero) e' sempre sostituita: nessun comando di sistema reale parte
durante i test.
"""
import time

import pytest

from test_bot_telegram import _carica_modulo


@pytest.fixture
def bot(monkeypatch, tmp_path):
    modulo = _carica_modulo()
    chiamate = []

    def tg_finta(metodo, attesa=20, **dati):
        chiamate.append({"metodo": metodo, "dati": dati})
        return {"ok": True, "result": {}}

    monkeypatch.setattr(modulo, "tg", tg_finta)
    monkeypatch.setattr(modulo, "LOG", str(tmp_path / "bot.log"))
    modulo._CHIAMATE = chiamate
    modulo._attesa.clear()
    modulo._in_corso = None
    modulo._ULTIMO_RESPINTO.clear()
    return modulo


class _StoricoFinto:
    """Sostituisce l'intero modulo photocarcifo-ban-alert.py per i test:
    leggi_snapshot() legge da un dizionario Python passato dal test,
    invece che dal file reale /var/lib/photocarcifo/ban-storico.json."""

    def __init__(self, dati):
        self.dati = dati

    def leggi_snapshot(self, ip):
        return self.dati.get(ip)


def _fail2ban_status(jail_a_ip):
    """Un finto esegui() che risponde a 'fail2ban-client status <jail>'
    con il formato reale (solo la riga che il codice legge davvero)."""
    def finto(argomenti, secondi=120):
        if argomenti[:2] == ["fail2ban-client", "status"] and len(argomenti) > 2:
            jail = argomenti[2]
            ips = jail_a_ip.get(jail, [])
            return f"Banned IP list:\t{' '.join(ips)}" if ips else "Banned IP list:\t"
        return ""
    return finto


SNAPSHOT_COMPLETO = {
    "jail": "photocarcifo-scansioni",
    "motivo": "Scansione di file/percorsi sensibili — tentativi su /.env",
    "tentativi": "27",
    "path": ["/.env", "/wp-admin", "/phpmyadmin"],
    "status": "404",
    "user_agent": "python-requests/2.28",
    "geo": {"country": "Canada", "region": "Ontario", "city": "Toronto",
            "isp": "Microsoft Corporation", "org": None, "asn": "AS8075",
            "rete": "Datacenter/hosting"},
    "abuse": {"score": 100, "segnalazioni": 1448},
    "quando": "2026-08-26T15:47:00+00:00",
}


# --------------------------------------------------------- rete reale: NO

def test_nessuna_chiamata_di_rete_durante_bloccati(bot, monkeypatch):
    import urllib.request

    def esplodi(*a, **k):
        raise AssertionError("chiamata di rete reale intercettata")

    monkeypatch.setattr(urllib.request, "urlopen", esplodi)
    monkeypatch.setattr(bot, "esegui", _fail2ban_status(
        {"photocarcifo-scansioni": ["20.48.160.90"]}))
    monkeypatch.setattr(bot, "_modulo_ban_alert",
                        lambda: _StoricoFinto({"20.48.160.90": SNAPSHOT_COMPLETO}))
    bot.gestisci("/bloccati")
    # nessuna eccezione sollevata: 0 chiamate di rete confermate


def test_nessuna_chiamata_telegram_reale(bot, monkeypatch):
    import urllib.request

    def esplodi(*a, **k):
        raise AssertionError("chiamata di rete reale intercettata")

    monkeypatch.setattr(urllib.request, "urlopen", esplodi)
    monkeypatch.setattr(bot, "esegui", _fail2ban_status({}))
    r = bot.gestisci("/bloccati")
    assert "Nessun indirizzo bloccato" in r


# ------------------------------------------------------------- dettagli

def test_ip_con_dettagli_completi(bot, monkeypatch):
    monkeypatch.setattr(bot, "esegui", _fail2ban_status(
        {"photocarcifo-scansioni": ["20.48.160.90"]}))
    monkeypatch.setattr(bot, "_modulo_ban_alert",
                        lambda: _StoricoFinto({"20.48.160.90": SNAPSHOT_COMPLETO}))
    r = bot.gestisci("/bloccati")
    assert "20.48.160.90" in r
    assert "Scansione di file" in r
    assert "27" in r
    assert "/.env" in r and "/wp-admin" in r
    assert "Toronto" in r and "Canada" in r
    assert "Microsoft Corporation" in r
    assert "AS8075" in r
    assert "100%" in r
    assert "1448" in r
    assert "26/08" in r


def test_motivo_mostrato_chiaramente(bot, monkeypatch):
    monkeypatch.setattr(bot, "esegui", _fail2ban_status(
        {"photocarcifo-login": ["1.2.3.4"]}))
    snap = dict(SNAPSHOT_COMPLETO, motivo="Tentativi di password ripetuti (brute force)")
    monkeypatch.setattr(bot, "_modulo_ban_alert",
                        lambda: _StoricoFinto({"1.2.3.4": snap}))
    r = bot.gestisci("/bloccati")
    assert "Motivo: Tentativi di password ripetuti (brute force)" in r


def test_geoip_presente(bot, monkeypatch):
    monkeypatch.setattr(bot, "esegui", _fail2ban_status(
        {"photocarcifo-scansioni": ["9.9.9.9"]}))
    monkeypatch.setattr(bot, "_modulo_ban_alert",
                        lambda: _StoricoFinto({"9.9.9.9": SNAPSHOT_COMPLETO}))
    r = bot.gestisci("/bloccati")
    assert "🌍" in r
    assert "Toronto" in r


def test_geoip_assente(bot, monkeypatch):
    snap = dict(SNAPSHOT_COMPLETO, geo=None)
    monkeypatch.setattr(bot, "esegui", _fail2ban_status(
        {"photocarcifo-scansioni": ["9.9.9.9"]}))
    monkeypatch.setattr(bot, "_modulo_ban_alert",
                        lambda: _StoricoFinto({"9.9.9.9": snap}))
    r = bot.gestisci("/bloccati")
    assert "🌍" not in r
    assert "None" not in r


def test_reputazione_presente(bot, monkeypatch):
    monkeypatch.setattr(bot, "esegui", _fail2ban_status(
        {"photocarcifo-scansioni": ["9.9.9.9"]}))
    monkeypatch.setattr(bot, "_modulo_ban_alert",
                        lambda: _StoricoFinto({"9.9.9.9": SNAPSHOT_COMPLETO}))
    r = bot.gestisci("/bloccati")
    assert "Reputazione: 100%" in r
    assert "Segnalazioni: 1448" in r


def test_reputazione_assente(bot, monkeypatch):
    snap = dict(SNAPSHOT_COMPLETO, abuse=None)
    monkeypatch.setattr(bot, "esegui", _fail2ban_status(
        {"photocarcifo-scansioni": ["9.9.9.9"]}))
    monkeypatch.setattr(bot, "_modulo_ban_alert",
                        lambda: _StoricoFinto({"9.9.9.9": snap}))
    r = bot.gestisci("/bloccati")
    assert "Reputazione" not in r


def test_ip_storico_senza_dettagli(bot, monkeypatch):
    """Un IP bannato prima dell'introduzione dello storico: nessuno
    snapshot salvato, nessuna causa inventata."""
    monkeypatch.setattr(bot, "esegui", _fail2ban_status(
        {"sshd": ["203.0.113.9"]}))
    monkeypatch.setattr(bot, "_modulo_ban_alert", lambda: _StoricoFinto({}))
    r = bot.gestisci("/bloccati")
    assert "203.0.113.9" in r
    assert "dato storico non disponibile" in r
    assert "sshd" in r  # almeno la jail resta visibile


# ----------------------------------------------------------- paginazione

def test_molti_ip_paginazione(bot, monkeypatch):
    ips = [f"10.0.0.{i}" for i in range(1, 13)]  # 12 IP, pagina da 5
    monkeypatch.setattr(bot, "esegui", _fail2ban_status(
        {"photocarcifo-scansioni": ips}))
    storico = {ip: dict(SNAPSHOT_COMPLETO) for ip in ips}
    monkeypatch.setattr(bot, "_modulo_ban_alert", lambda: _StoricoFinto(storico))

    pagina1 = bot.gestisci("/bloccati")
    assert "Pagina 1/3" in pagina1
    assert "10.0.0.1" in pagina1
    assert "10.0.0.6" not in pagina1  # sulla pagina 2

    pagina2 = bot.gestisci("/bloccati 2")
    assert "Pagina 2/3" in pagina2
    assert "10.0.0.6" in pagina2
    assert "10.0.0.1" not in pagina2

    pagina3 = bot.gestisci("/bloccati 3")
    assert "Pagina 3/3" in pagina3


def test_pagina_oltre_il_massimo_torna_ultima(bot, monkeypatch):
    """Con una sola pagina possibile, /bloccati 99 non deve dare una
    lista vuota: torna alla pagina 1 (l'unica che esiste). Il piede
    "Pagina x/y" compare solo quando ci sono davvero piu' pagine."""
    ips = [f"10.0.0.{i}" for i in range(1, 4)]
    monkeypatch.setattr(bot, "esegui", _fail2ban_status(
        {"photocarcifo-scansioni": ips}))
    storico = {ip: dict(SNAPSHOT_COMPLETO) for ip in ips}
    monkeypatch.setattr(bot, "_modulo_ban_alert", lambda: _StoricoFinto(storico))
    r = bot.gestisci("/bloccati 99")
    assert "10.0.0.1" in r
    assert "Pagina" not in r


# ---------------------------------------------------------------- filtri

def test_filtro_oggi(bot, monkeypatch):
    from datetime import datetime, timezone
    oggi = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ip_oggi, ip_ieri = "10.0.0.1", "10.0.0.2"
    monkeypatch.setattr(bot, "esegui", _fail2ban_status(
        {"photocarcifo-scansioni": [ip_oggi, ip_ieri]}))
    storico = {
        ip_oggi: dict(SNAPSHOT_COMPLETO, quando=f"{oggi}T10:00:00+00:00"),
        ip_ieri: dict(SNAPSHOT_COMPLETO, quando="2020-01-01T10:00:00+00:00"),
    }
    monkeypatch.setattr(bot, "_modulo_ban_alert", lambda: _StoricoFinto(storico))
    r = bot.gestisci("/bloccati oggi")
    assert ip_oggi in r
    assert ip_ieri not in r


def test_filtro_scansioni(bot, monkeypatch):
    ip_scansione, ip_bruteforce = "10.0.0.1", "10.0.0.2"
    monkeypatch.setattr(bot, "esegui", _fail2ban_status(
        {"photocarcifo-scansioni": [ip_scansione], "photocarcifo-login": [ip_bruteforce]}))
    storico = {
        ip_scansione: dict(SNAPSHOT_COMPLETO, motivo="Scansione di file sensibili"),
        ip_bruteforce: dict(SNAPSHOT_COMPLETO, motivo="Tentativi brute force"),
    }
    monkeypatch.setattr(bot, "_modulo_ban_alert", lambda: _StoricoFinto(storico))
    r = bot.gestisci("/bloccati scansioni")
    assert ip_scansione in r
    assert ip_bruteforce not in r


def test_filtro_sconosciuto_da_errore_chiaro(bot, monkeypatch):
    monkeypatch.setattr(bot, "esegui", _fail2ban_status(
        {"photocarcifo-scansioni": ["10.0.0.1"]}))
    monkeypatch.setattr(bot, "_modulo_ban_alert",
                        lambda: _StoricoFinto({"10.0.0.1": SNAPSHOT_COMPLETO}))
    r = bot.gestisci("/bloccati marziani")
    assert "non riconosciuto" in r.lower()
    assert "10.0.0.1" not in r  # non mostra la lista, solo l'errore


# ------------------------------------------------------------ autorizzazione

def test_bloccati_richiede_autorizzazione(bot, monkeypatch, tmp_path):
    """Stesso schema del resto del bot: autorizzato() e' il controllo
    unico, prima di gestisci(). Qui si verifica solo che /bloccati non
    sia esente da quel controllo — usando lo stesso giro completo di
    test_bot_telegram_sicurezza.py."""
    from test_bot_telegram_sicurezza import _msg_privato

    monkeypatch.setattr(bot, "esegui", _fail2ban_status(
        {"photocarcifo-scansioni": ["10.0.0.1"]}))
    monkeypatch.setattr(bot, "_modulo_ban_alert",
                        lambda: _StoricoFinto({"10.0.0.1": SNAPSHOT_COMPLETO}))

    msg_estraneo = _msg_privato("999999999", "/bloccati")
    assert bot.autorizzato(msg_estraneo) is False
    # Il giro completo (main()) non chiamerebbe mai gestisci() per questo
    # messaggio: verificato a parte in test_bot_telegram_sicurezza.py con
    # tutti i comandi, incluso "bloccati" nella lista parametrizzata.


# ------------------------------------------------------------------ /sblocca

def test_ip_sbloccato_non_compare_piu(bot, monkeypatch):
    """Dopo /sblocca, fail2ban-client status non elenca piu' l'IP: dato
    che _bloccati_grezzi() legge SEMPRE lo stato attuale (mai una lista
    salvata), un IP sbloccato sparisce automaticamente da /bloccati senza
    bisogno di alcuna pulizia dello storico."""
    monkeypatch.setattr(bot, "esegui", _fail2ban_status({}))  # nessuno bloccato ora
    storico = {"10.0.0.1": SNAPSHOT_COMPLETO}  # storico ancora presente
    monkeypatch.setattr(bot, "_modulo_ban_alert", lambda: _StoricoFinto(storico))
    r = bot.gestisci("/bloccati")
    assert "Nessun indirizzo bloccato" in r
    assert "10.0.0.1" not in r
