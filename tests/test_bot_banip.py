"""/banip e /unbanip, il ban manuale dal bot Telegram (script/
photocarcifo-bot.py).

Riusano la stessa infrastruttura di /bloccati e /sblocca: fail2ban come
unica fonte di verita' su chi e' bloccato ADESSO (_bloccati_grezzi(),
sempre attraverso una esegui() finta — nessun comando di sistema reale
parte durante i test), e lo storico di photocarcifo-ban-alert.py per il
motivo mostrato da /bloccati. Nessuna chiamata di rete reale (tg() e'
sempre sostituita, stessa fixture di test_bot_telegram.py).

Cosa NON puo' testare questo file, e perche': il blocco vero avviene
fuori dal processo Python, in una regola nftables scritta da fail2ban —
verificato a mano sul sistema reale (ban di prova su 203.0.113.5,
regola "reject" comparsa in `nft list ruleset`, poi tolta; e persistenza
attraverso un `systemctl restart fail2ban`), non riproducibile in un test
che sostituisce esegui() per principio, come fa il resto di questa
suite."""
import ipaddress

import pytest

from test_bot_telegram import _carica_modulo, _messaggi_inviati


@pytest.fixture
def bot(monkeypatch, tmp_path):
    modulo = _carica_modulo()
    chiamate = []

    def tg_finta(metodo, attesa=20, **dati):
        chiamate.append({"metodo": metodo, "dati": dati})
        return {"ok": True, "result": {"message_id": len(chiamate)}}

    monkeypatch.setattr(modulo, "tg", tg_finta)
    monkeypatch.setattr(modulo, "LOG", str(tmp_path / "bot.log"))
    modulo._CHIAMATE = chiamate
    modulo._attesa.clear()
    modulo._in_corso = None
    modulo._ULTIMO_RESPINTO.clear()
    return modulo


class _StoricoFinto:
    """Sostituisce photocarcifo-ban-alert.py: leggi_snapshot legge da un
    dizionario passato dal test invece che dal file reale, salva_snapshot
    registra le chiamate invece di scrivere su disco — cosi' un test puo'
    verificare che cmd_banip l'abbia chiamata, con quali argomenti."""

    def __init__(self, dati=None):
        self.dati = dati or {}
        self.salvataggi = []

    def leggi_snapshot(self, ip):
        return self.dati.get(ip)

    def salva_snapshot(self, jail, ip, tentativi, motivo, principali,
                       status, ua, geo, abuse):
        self.salvataggi.append({"jail": jail, "ip": ip, "motivo": motivo})
        self.dati[ip] = {"jail": jail, "motivo": motivo}


def _fail2ban_status(jail_a_ip):
    """Stesso finto esegui() di test_bot_bloccati.py: risponde a
    'fail2ban-client status <jail>' con il formato reale, registra ogni
    comando ricevuto perche' i test possano verificare cosa e' stato
    chiesto davvero a fail2ban."""
    chiamate = []

    def finto(argomenti, secondi=120):
        chiamate.append(list(argomenti))
        if argomenti[:2] == ["fail2ban-client", "status"] and len(argomenti) > 2:
            jail = argomenti[2]
            ips = jail_a_ip.get(jail, [])
            return f"Banned IP list:\t{' '.join(ips)}" if ips else "Banned IP list:\t"
        return "1"
    finto.chiamate = chiamate
    return finto


def _prepara(bot, monkeypatch, jail_a_ip=None, storico=None):
    finto_esegui = _fail2ban_status(jail_a_ip or {})
    monkeypatch.setattr(bot, "esegui", finto_esegui)
    finto_storico = storico or _StoricoFinto()
    monkeypatch.setattr(bot, "_modulo_ban_alert", lambda: finto_storico)
    return finto_esegui, finto_storico


# ------------------------------------------------------------ /banip


def test_banip_indirizzo_valido_lo_banna(bot, monkeypatch):
    """Test 1: admin autorizzato, /banip su un IP valido non ancora
    bloccato → la jail manuale lo banna, lo storico registra il motivo,
    la risposta conferma.

    8.8.8.8 e non un TEST-NET (192.0.2.0/24, 198.51.100.0/24,
    203.0.113.0/24): sono gli indirizzi che si penserebbe "di prova"
    sicuri da usare qui, ma ipaddress li considera is_private (sono
    riservati alla documentazione), quindi _ip_protetto li respingerebbe
    — verificato incontrandolo, non supposto."""
    finto, storico = _prepara(bot, monkeypatch)
    risposta = bot.cmd_banip("8.8.8.8")
    assert "bannato" in risposta
    assert "8.8.8.8" in risposta
    comandi_banip = [c for c in finto.chiamate
                     if c[:3] == ["fail2ban-client", "set", bot.JAIL_MANUALE]
                     and "banip" in c]
    assert comandi_banip == [["fail2ban-client", "set", bot.JAIL_MANUALE,
                              "banip", "8.8.8.8"]]
    assert storico.salvataggi == [
        {"jail": bot.JAIL_MANUALE, "ip": "8.8.8.8",
         "motivo": "Ban manuale (bot Telegram)"}]


def test_banip_indirizzo_ipv6_valido(bot, monkeypatch):
    """La validazione con ipaddress accetta IPv6 quanto IPv4, come
    richiesto: nessun trattamento speciale, stessa funzione. Non
    2001:db8::1 (il "documentation range" IPv6): stesso discorso di
    8.8.8.8 qui sopra, ipaddress lo considera is_private."""
    finto, _ = _prepara(bot, monkeypatch)
    risposta = bot.cmd_banip("2606:4700:4700::1111")
    assert "bannato" in risposta
    assert ["fail2ban-client", "set", bot.JAIL_MANUALE, "banip",
            "2606:4700:4700::1111"] in finto.chiamate


def test_banip_stesso_indirizzo_due_volte_non_duplica(bot, monkeypatch):
    """Test 2: un IP gia' bloccato (in una jail qualunque, non solo
    quella manuale) non viene bannato una seconda volta — nessuna nuova
    chiamata banip, risposta che lo dice chiaramente."""
    finto, storico = _prepara(
        bot, monkeypatch, jail_a_ip={bot.JAIL_MANUALE: ["8.8.8.8"]})
    risposta = bot.cmd_banip("8.8.8.8")
    assert "gia'" in risposta
    assert bot.JAIL_MANUALE in risposta
    comandi_banip = [c for c in finto.chiamate if "banip" in c]
    assert comandi_banip == []  # nessun secondo ban
    assert storico.salvataggi == []  # nessuna nuova voce nello storico


@pytest.mark.parametrize("indirizzo", [
    "", "ciao", "999.999.999.999", "1.2.3.4 qualcosa", "1.2.3.4/24",
    "1.2.3", "   ",
])
def test_banip_indirizzo_invalido_non_tocca_niente(bot, monkeypatch, indirizzo):
    """Test 4: nessun indirizzo malformato arriva a fail2ban-client, ne'
    allo storico — la validazione con ipaddress.ip_address() (non una
    regex artigianale) respinge tutto cio' che non e' un indirizzo IP
    completo e solo quello."""
    finto, storico = _prepara(bot, monkeypatch)
    risposta = bot.cmd_banip(indirizzo)
    assert "valido" in risposta or "Serve un indirizzo" in risposta
    assert finto.chiamate == []
    assert storico.salvataggi == []


@pytest.mark.parametrize("indirizzo", [
    "127.0.0.1", "::1", "192.168.1.50", "10.0.0.5", "172.16.0.1",
    "169.254.1.1",  # link-local
    "224.0.0.1",    # multicast
    "100.64.0.1",   # CGNAT/Tailscale: is_private E is_global sono
                    # entrambi falsi per questo intervallo, l'unico caso
                    # in cui ipaddress non li tratta come opposti — senza
                    # "not is_global" in _ip_protetto sarebbe passato
                    # per pubblico (trovato dalla security review, non
                    # supposto).
    "::ffff:192.168.1.1",  # IPv4-mapped: la forma che si proverebbe per
                           # prima per aggirare un controllo scritto
                           # pensando solo a indirizzi IPv4 "normali".
    "::ffff:127.0.0.1",
    "::127.0.0.1",  # forma IPv6 deprecata dello stesso loopback.
])
def test_banip_indirizzo_protetto_viene_rifiutato(bot, monkeypatch, indirizzo):
    """Test 8: localhost e reti interne non si bannano mai, nemmeno a
    comando esplicito — verificato di persona che fail2ban-client NON
    applica da solo ignoreip a un ban manuale (ha bannato 127.0.0.1
    quando richiesto direttamente): la protezione deve stare qui."""
    finto, storico = _prepara(bot, monkeypatch)
    risposta = bot.cmd_banip(indirizzo)
    assert "protetto" in risposta
    assert finto.chiamate == []
    assert storico.salvataggi == []


def test_banip_indirizzo_con_zone_id_ipv6(bot, monkeypatch):
    """fe80::1%eth0 (zone id, sintassi valida per un link-local IPv6) —
    caso a parte perche' ipaddress.ip_address() lo accetta solo in
    Python recenti; se il sistema in produzione ne avesse uno piu'
    vecchio il comando deve comunque fallire in modo pulito (indirizzo
    non valido), mai bannare qualcosa a caso."""
    finto, storico = _prepara(bot, monkeypatch)
    risposta = bot.cmd_banip("fe80::1%eth0")
    assert "protetto" in risposta or "valido" in risposta
    assert finto.chiamate == []
    assert storico.salvataggi == []


def test_banip_ignoreip_non_e_una_rete_di_sicurezza_di_fail2ban(bot):
    """Documenta il fatto verificato sul sistema reale, non solo
    supposto: ipaddress conferma che 127.0.0.1 e ::1 risultano
    'protetti' per is_loopback anche senza consultare la lista ignoreip
    di fail2ban, che infatti (provato con fail2ban-client davvero, non
    in questo test) non li avrebbe fermati da sola."""
    assert bot._ip_protetto(ipaddress.ip_address("127.0.0.1"))
    assert bot._ip_protetto(ipaddress.ip_address("::1"))


def test_banip_cgnat_non_passa_per_pubblico(bot):
    """Il difetto trovato dalla security review, isolato dal resto:
    is_private da solo non basta per 100.64.0.0/10."""
    ip = ipaddress.ip_address("100.64.0.1")
    assert not ip.is_private  # e' proprio questo il tranello
    assert bot._ip_protetto(ip)  # ma _ip_protetto lo prende comunque


# ------------------------------------------------------------ /unbanip


def test_unbanip_rimuove_il_ban(bot, monkeypatch):
    """Test 3: un IP bloccato in una jail viene sbloccato in quella
    stessa jail, qualunque essa sia (non solo quella manuale)."""
    finto, _ = _prepara(
        bot, monkeypatch,
        jail_a_ip={"photocarcifo-login": ["203.0.113.5"]})
    risposta = bot.cmd_unbanip("203.0.113.5")
    assert "sbloccato" in risposta
    assert ["fail2ban-client", "set", "photocarcifo-login",
            "unbanip", "203.0.113.5"] in finto.chiamate


def test_unbanip_indirizzo_non_bloccato(bot, monkeypatch):
    finto, _ = _prepara(bot, monkeypatch)
    risposta = bot.cmd_unbanip("203.0.113.5")
    assert "non risulta bloccato" in risposta
    assert not any("unbanip" in c for c in finto.chiamate)


@pytest.mark.parametrize("indirizzo", ["", "ciao", "1.2.3.4.5"])
def test_unbanip_indirizzo_invalido(bot, monkeypatch, indirizzo):
    finto, _ = _prepara(bot, monkeypatch)
    risposta = bot.cmd_unbanip(indirizzo)
    assert "valido" in risposta or "Serve un indirizzo" in risposta
    assert finto.chiamate == []


# ------------------------------------------------- /bloccati e /sblocca
# vedono i ban manuali come tutti gli altri (nessun sistema separato)


def test_bloccati_vede_anche_i_ban_manuali(bot, monkeypatch):
    """La jail manuale e' nell'elenco CARCERI: /bloccati la legge come le
    altre, senza codice dedicato."""
    _prepara(bot, monkeypatch,
             jail_a_ip={bot.JAIL_MANUALE: ["203.0.113.5"]},
             storico=_StoricoFinto({"203.0.113.5": {
                 "jail": bot.JAIL_MANUALE,
                 "motivo": "Ban manuale (bot Telegram)"}}))
    risposta = bot.cmd_bloccati()
    assert "203.0.113.5" in risposta
    assert "Ban manuale" in risposta


def test_sblocca_libera_anche_i_ban_manuali(bot, monkeypatch):
    """/sblocca (la via di scampo d'emergenza) itera CARCERI, che ora
    include la jail manuale: un ban manuale sbagliato si toglie anche
    da li', non resta un'eccezione nascosta."""
    finto, _ = _prepara(
        bot, monkeypatch,
        jail_a_ip={bot.JAIL_MANUALE: ["203.0.113.5"],
                  "photocarcifo-login": ["198.51.100.9"]})
    risposta = bot.cmd_sblocca("SI")
    assert "Liberati 2" in risposta
    assert ["fail2ban-client", "set", bot.JAIL_MANUALE,
            "unbanip", "203.0.113.5"] in finto.chiamate
    assert ["fail2ban-client", "set", "photocarcifo-login",
            "unbanip", "198.51.100.9"] in finto.chiamate


# --------------------------------------------- comando invocato dal giro


def test_gestisci_passa_lindirizzo_intero_a_banip(bot, monkeypatch):
    """banip e' in CON_ARGOMENTO_LIBERO: l'indirizzo arriva intatto alla
    funzione, non ridotto a 'SI'/'' come i comandi con sola conferma."""
    _prepara(bot, monkeypatch)
    risposta = bot.gestisci("/banip 8.8.8.8")
    assert "8.8.8.8" in risposta
    assert "bannato" in risposta


def test_gestisci_banip_senza_argomento(bot, monkeypatch):
    _prepara(bot, monkeypatch)
    risposta = bot.gestisci("/banip")
    assert "Serve un indirizzo" in risposta
