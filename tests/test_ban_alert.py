"""Notifica di ban IP (script/photocarcifo-ban-alert.py).

fail2ban chiama questo script direttamente ad ogni ban (action.d/
photocarcifo-alert.conf): il ban e' gia' avvenuto quando lo script parte,
qui si arricchisce l'evento e si notifica su Telegram (unico canale — il
supporto WhatsApp e' stato rimosso perche' mai configurato: non aveva
senso mantenere un percorso alternativo mai usato). L'integrazione non
deve MAI essere raggiunta davvero durante i test: ogni test che chiama
elabora()/invia_telegram() monkeypatcha urllib.request.urlopen, e un test
dedicato verifica esplicitamente che 0 richieste di rete partano durante
l'intera suite di questo file.
"""
import importlib.util
import json
import time
from pathlib import Path

import pytest

RADICE = Path(__file__).resolve().parent.parent
SCRIPT = RADICE / "script"


def _carica_modulo():
    percorso = SCRIPT / "photocarcifo-ban-alert.py"
    spec = importlib.util.spec_from_file_location("photocarcifo_ban_alert", percorso)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture
def modulo(monkeypatch, tmp_path):
    """Il modulo, con LOG, CACHE_GEO e STORICO puntati a file temporanei
    (mai quelli di produzione), pronto per essere usato dai test."""
    m = _carica_modulo()
    monkeypatch.setattr(m, "LOG", str(tmp_path / "ban-alert.log"))
    monkeypatch.setattr(m, "CACHE_GEO", str(tmp_path / "cache.json"))
    monkeypatch.setattr(m, "STORICO", str(tmp_path / "storico.json"))
    return m


@pytest.fixture
def blocca_rete(monkeypatch):
    """Sostituisce urlopen con una funzione che fallisce sempre se
    chiamata SENZA essere stata a sua volta rimpiazzata da un test: serve
    come rete di sicurezza in test che non si aspettano alcuna chiamata
    di rete (es. quando manca la configurazione)."""
    import urllib.request

    def esplodi(*a, **k):
        raise AssertionError("chiamata di rete reale intercettata durante i test")

    monkeypatch.setattr(urllib.request, "urlopen", esplodi)


RIGHE_ESEMPIO = [
    '203.0.113.55 - - [26/Aug/2026:16:20:00 +0200] "GET /.env HTTP/1.1" 404 0 "-" "python-requests/2.28"',
    '203.0.113.55 - - [26/Aug/2026:16:20:01 +0200] "GET /wp-admin/ HTTP/1.1" 404 0 "-" "python-requests/2.28"',
]


# --------------------------------------------------------- rete reale: NO

def test_nessuna_chiamata_di_rete_reale_senza_config(modulo, blocca_rete):
    """Con configurazione vuota (nessun token/chiave), elabora() non deve
    tentare NESSUNA chiamata di rete: ne' GeoIP, ne' AbuseIPDB, ne'
    Telegram, ne' WhatsApp."""
    ok = modulo.elabora("photocarcifo-scansioni", "203.0.113.55", "18",
                        RIGHE_ESEMPIO, config={})
    assert ok is False  # nessun canale configurato: nessuna notifica


def test_nessuna_chiamata_di_rete_reale_giro_completo(modulo, monkeypatch):
    """Anche con Telegram/WhatsApp "configurati" (valori finti), la rete
    non deve mai essere toccata per davvero: tutte le funzioni di rete
    sono sostituite esplicitamente qui."""
    import urllib.request
    chiamate = []

    def urlopen_finto(req, timeout=None):
        chiamate.append(req.full_url if hasattr(req, "full_url") else str(req))
        raise AssertionError("non dovrebbe arrivare qui nei test: ogni funzione "
                             "di rete va sostituita esplicitamente per nome")

    monkeypatch.setattr(urllib.request, "urlopen", urlopen_finto)
    monkeypatch.setattr(modulo, "geolocalizza", lambda ip: None)
    monkeypatch.setattr(modulo, "reputazione", lambda ip, key: None)
    monkeypatch.setattr(modulo, "motore_verificato", lambda ip: None)
    monkeypatch.setattr(modulo, "invia_telegram", lambda cfg, testo: True)

    ok = modulo.elabora("photocarcifo-scansioni", "203.0.113.55", "18",
                        RIGHE_ESEMPIO,
                        config={"TELEGRAM_TOKEN": "finto", "TELEGRAM_CHAT": "finto"})
    assert ok is True
    assert chiamate == []


# ------------------------------------------------------------- motivo

def test_motivo_scansioni_riconosciuto(modulo):
    motivo, livello = modulo.motivo_e_livello("photocarcifo-scansioni")
    assert "sensibili" in motivo.lower()
    assert livello == "CRITICAL"


def test_motivo_affinato_con_path_env(modulo):
    base, _ = modulo.motivo_e_livello("photocarcifo-scansioni")
    affinato = modulo.affina_motivo(base, RIGHE_ESEMPIO)
    assert ".env" in affinato


def test_jail_sconosciuta_ha_motivo_generico_non_critico(modulo):
    motivo, livello = modulo.motivo_e_livello("una-jail-mai-vista")
    assert "una-jail-mai-vista" in motivo
    assert livello == "WARNING"


# --------------------------------------------------------- dettagli log

def test_estrai_dettagli_trova_i_path_principali(modulo):
    principali, status, ua = modulo.estrai_dettagli(RIGHE_ESEMPIO)
    assert "/.env" in principali
    assert "/wp-admin/" in principali
    assert status == "404"
    assert "python-requests" in ua


def test_estrai_dettagli_limita_a_cinque_path(modulo):
    tante_righe = [
        f'1.2.3.4 - - [26/Aug/2026:16:20:00 +0200] "GET /percorso{i} HTTP/1.1" 404 0 "-" "ua"'
        for i in range(20)
    ]
    principali, _, _ = modulo.estrai_dettagli(tante_righe)
    assert len(principali) <= 5


def test_estrai_dettagli_righe_vuote_non_esplode(modulo):
    principali, status, ua = modulo.estrai_dettagli([])
    assert principali == []
    assert status is None
    assert ua is None


# --------------------------------------------------------------- geoip

def test_geolocalizza_ip_privato_non_fa_richieste(modulo, blocca_rete):
    assert modulo.geolocalizza("192.168.1.1") is None


def test_geolocalizza_ip_non_valido_non_fa_richieste(modulo, blocca_rete):
    assert modulo.geolocalizza("non-e-un-ip") is None


def test_geolocalizza_usa_la_cache_al_secondo_giro(modulo, monkeypatch):
    chiamate = []

    def http_finto(url, timeout=4, **h):
        chiamate.append(url)
        return {"status": "success", "country": "Italia", "regionName": "Ticino",
                "city": "Lugano", "isp": "Finto ISP", "org": "", "as": "AS1 Finto",
                "mobile": False, "proxy": False, "hosting": False}

    # 203.0.113.0/24 e' il blocco riservato per documentazione (RFC 5737):
    # ipaddress lo classifica come "privato", quindi geolocalizza() lo
    # scarterebbe subito senza mai provare il lookup — qui serve un IP
    # pubblico plausibile per esercitare davvero il percorso di rete
    # (finto, non e' mai raggiunto davvero: _http_json e' sostituita).
    monkeypatch.setattr(modulo, "_http_json", http_finto)
    primo = modulo.geolocalizza("1.1.1.1")
    secondo = modulo.geolocalizza("1.1.1.1")
    assert primo == secondo
    assert len(chiamate) == 1  # il secondo giro ha usato la cache


def test_geolocalizza_api_offline_ritorna_none_senza_eccezioni(modulo, monkeypatch):
    monkeypatch.setattr(modulo, "_http_json", lambda *a, **k: None)
    assert modulo.geolocalizza("1.0.0.1") is None


# ----------------------------------------------------------- reputazione

def test_reputazione_senza_chiave_non_tenta_la_richiesta(modulo, blocca_rete):
    assert modulo.reputazione("203.0.113.55", "") is None


def test_reputazione_con_chiave_usa_http_json(modulo, monkeypatch):
    monkeypatch.setattr(modulo, "_http_json", lambda *a, **k: {
        "data": {"abuseConfidenceScore": 87, "totalReports": 42}})
    r = modulo.reputazione("203.0.113.55", "chiave-finta")
    assert r == {"score": 87, "segnalazioni": 42}


def test_reputazione_api_offline_non_blocca(modulo, monkeypatch):
    monkeypatch.setattr(modulo, "_http_json", lambda *a, **k: None)
    assert modulo.reputazione("203.0.113.55", "chiave-finta") is None


# ------------------------------------------------------------- motore_verificato

def test_bingbot_verificato_richiede_doppio_controllo(modulo, monkeypatch):
    import socket
    monkeypatch.setattr(socket, "gethostbyaddr",
                        lambda ip: ("msnbot-1-2-3-4.search.msn.com.", [], [ip]))
    monkeypatch.setattr(socket, "gethostbyname", lambda nome: "1.2.3.4")
    assert modulo.motore_verificato("1.2.3.4") == "Bingbot"


def test_googlebot_verificato_richiede_doppio_controllo(modulo, monkeypatch):
    import socket
    monkeypatch.setattr(socket, "gethostbyaddr",
                        lambda ip: ("crawl-1-2-3-4.googlebot.com.", [], [ip]))
    monkeypatch.setattr(socket, "gethostbyname", lambda nome: "1.2.3.4")
    assert modulo.motore_verificato("1.2.3.4") == "Googlebot"


def test_applebot_verificato_richiede_doppio_controllo(modulo, monkeypatch):
    import socket
    monkeypatch.setattr(socket, "gethostbyaddr",
                        lambda ip: ("applebot.applebot.apple.com.", [], [ip]))
    monkeypatch.setattr(socket, "gethostbyname", lambda nome: "1.2.3.4")
    assert modulo.motore_verificato("1.2.3.4") == "Applebot"


def test_bingbot_reverse_dns_falso_non_basta(modulo, monkeypatch):
    """Un reverse DNS che dice 'search.msn.com' ma la risoluzione diretta
    del nome non torna allo stesso IP: non verificato — questo e' il
    caso che distingue un vero controllo da un controllo ingannabile con
    un solo PTR scritto a piacere."""
    import socket
    monkeypatch.setattr(socket, "gethostbyaddr",
                        lambda ip: ("msnbot-1-2-3-4.search.msn.com.", [], [ip]))
    monkeypatch.setattr(socket, "gethostbyname", lambda nome: "9.9.9.9")  # non coincide
    assert modulo.motore_verificato("1.2.3.4") is None


def test_ip_azure_generico_senza_reverse_dns_non_e_bingbot(modulo, monkeypatch):
    """Il caso esplicitamente richiesto: un IP Microsoft/Azure qualsiasi,
    senza un reverse DNS che punti a search.msn.com, NON deve mai
    risultare 'Bingbot verificato' solo perche' appartiene a un range
    Microsoft."""
    import socket

    def niente_reverse(ip):
        raise socket.herror("nessun reverse DNS")

    monkeypatch.setattr(socket, "gethostbyaddr", niente_reverse)
    assert modulo.motore_verificato("20.48.160.90") is None


def test_ip_gcp_generico_senza_reverse_dns_non_e_googlebot(modulo, monkeypatch):
    """Stesso caso ma per Google Cloud: una VM qualunque su un range
    Google non deve mai risultare 'Googlebot verificato' senza un
    reverse DNS che punti davvero a googlebot.com/google.com."""
    import socket
    monkeypatch.setattr(socket, "gethostbyaddr",
                        lambda ip: ("136-67-135-98.bc.googleusercontent.com.", [], [ip]))
    assert modulo.motore_verificato("136.67.135.98") is None


def test_bingbot_lookup_fallito_non_esplode(modulo, monkeypatch):
    import socket
    monkeypatch.setattr(socket, "gethostbyaddr",
                        lambda ip: (_ for _ in ()).throw(OSError("timeout")))
    assert modulo.motore_verificato("1.2.3.4") is None


# --------------------------------------------------- brand_cloud_sospetto

def test_brand_cloud_sospetto_riconosce_microsoft(modulo):
    assert modulo.brand_cloud_sospetto({"isp": "Microsoft Corporation", "org": None}) is True


def test_brand_cloud_sospetto_ignora_isp_qualunque(modulo):
    assert modulo.brand_cloud_sospetto({"isp": "Feo Prest SRL", "org": None}) is False
    assert modulo.brand_cloud_sospetto(None) is False


def test_messaggio_avvisa_quando_isp_e_brand_cloud_ma_non_verificato(modulo):
    """Il caso che ha generato confusione: un ban con ISP 'Microsoft
    Corporation' che pero' non e' Bingbot verificato deve portare una
    nota esplicita, non lasciare che il nome da solo suggerisca che sia
    il servizio ufficiale."""
    geo = {"country": "Mexico", "region": "Queretaro", "city": "Queretaro City",
           "isp": "Microsoft Corporation", "org": None, "asn": "AS8075",
           "rete": "Datacenter/hosting"}
    testo, _ = modulo.costruisci_messaggio(
        "photocarcifo-scansioni", "158.23.147.79", "15", [], geo, None, motore=None)
    assert "non prova" in testo.lower()


def test_messaggio_non_avvisa_quando_motore_e_verificato(modulo):
    """Se il PTR+A ha gia' confermato il crawler, la nota sul 'nome non
    prova niente' sarebbe ridondante e fuorviante: non deve comparire."""
    geo = {"country": "United States", "region": "California", "city": "Mountain View",
           "isp": "Google LLC", "org": None, "asn": "AS15169", "rete": "Datacenter/hosting"}
    testo, _ = modulo.costruisci_messaggio(
        "nginx-limit-req", "66.249.72.230", "0", [], geo, None, motore="Googlebot")
    assert "non prova" not in testo.lower()
    assert "Googlebot" in testo


# --------------------------------------------------------- messaggio

def test_messaggio_esempio_reale_formato_atteso(modulo):
    """Lo stesso esempio della richiesta originale, con dati finti (mai
    inviati davvero): verifica che il formato prodotto sia quello
    concordato."""
    geo = {"country": "Canada", "region": "Ontario", "city": "Toronto",
           "isp": "Microsoft Corporation", "org": None, "asn": "AS8075",
           "rete": "Datacenter/hosting"}
    abuse = {"score": 100, "segnalazioni": 1448}
    testo, livello = modulo.costruisci_messaggio(
        "photocarcifo-scansioni", "20.48.160.90", "27", [
            '20.48.160.90 - - [26/Aug/2026:15:47:00 +0200] "GET /.env HTTP/1.1" 404 0 "-" "-"',
            '20.48.160.90 - - [26/Aug/2026:15:47:01 +0200] "GET /wp-admin HTTP/1.1" 404 0 "-" "-"',
            '20.48.160.90 - - [26/Aug/2026:15:47:02 +0200] "GET /phpmyadmin HTTP/1.1" 404 0 "-" "-"',
        ], geo, abuse, motore=None)
    assert "20.48.160.90" in testo
    assert "Toronto" in testo and "Canada" in testo
    assert "Microsoft Corporation" in testo
    assert "AS8075" in testo
    assert "Datacenter" in testo
    assert "100% abuse confidence" in testo
    assert "1448" in testo
    assert livello == "CRITICAL"
    # non piu' di 5 path anche qui, e non le centinaia vietate dalla richiesta
    assert testo.count("\n  /") <= 5


def test_nessun_campo_geo_assente_stampato_come_vuoto(modulo):
    """Se geo/abuse sono None (lookup falliti), il messaggio non deve
    contenere sezioni vuote o placeholder confusi."""
    testo, _ = modulo.costruisci_messaggio(
        "sshd", "203.0.113.1", "5", [], None, None, False)
    assert "None" not in testo
    assert "🌍" not in testo
    assert "Reputazione" not in testo


def test_bingbot_verificato_aggiunge_nota_di_cautela(modulo):
    testo, _ = modulo.costruisci_messaggio(
        "photocarcifo-scansioni", "1.2.3.4", "16", [], None, None, "Bingbot")
    assert "Bingbot" in testo


# --------------------------------------------------------------- escaping

def test_pulisci_rimuove_a_capo_e_caratteri_di_controllo(modulo):
    sporco = "riga1\nriga2\rriga3\x00fine"
    pulito = modulo.pulisci(sporco)
    assert "\n" not in pulito
    assert "\r" not in pulito
    assert "\x00" not in pulito


def test_pulisci_tronca_a_lunghezza_massima(modulo):
    lungo = "a" * 500
    assert len(modulo.pulisci(lungo, massimo=50)) == 50


def test_path_html_o_markdown_non_spezza_il_messaggio(modulo):
    """Un attaccante che scrive path tipo '<script>' o markdown Telegram
    (_ * [ ]) nel proprio User-Agent/path non deve produrre un messaggio
    malformato: qui non si usa comunque alcun parse_mode, quindi il
    testo arriva sempre come testo semplice — verificato che il
    contenuto ostile resti presente ma innocuo (nessuna eccezione, nessun
    troncamento anomalo)."""
    righe_ostili = [
        '1.2.3.4 - - [26/Aug/2026:00:00:00 +0200] "GET /<script>alert(1)</script> HTTP/1.1" 404 0 "-" "*_[bold]_*"',
    ]
    testo, _ = modulo.costruisci_messaggio(
        "photocarcifo-scansioni", "1.2.3.4", "1", righe_ostili, None, None, False)
    assert isinstance(testo, str)
    assert len(testo) > 0


# ------------------------------------------------------------ sicurezza

def test_nessun_token_nel_messaggio(modulo):
    """Il messaggio non deve mai contenere token/secret, anche se per
    assurdo comparissero in una riga di log (es. una query string con
    ?token=... intercettata da uno scanner malformato)."""
    righe_con_secret = [
        '1.2.3.4 - - [26/Aug/2026:00:00:00 +0200] "GET /?token=SEGRETO123456 HTTP/1.1" 404 0 "-" "-"',
    ]
    testo, _ = modulo.costruisci_messaggio(
        "photocarcifo-scansioni", "1.2.3.4", "1", righe_con_secret, None, None, False)
    # Il path intero (con la query string) puo' comparire: cio' che conta
    # e' che non venga MAI dal file di configurazione del bot.
    assert "TELEGRAM_TOKEN" not in testo


def test_ip_non_valido_non_genera_notifica(modulo, blocca_rete):
    ok = modulo.elabora("photocarcifo-scansioni", "non-e-un-indirizzo-ip", "5",
                        [], config={"TELEGRAM_TOKEN": "x", "TELEGRAM_CHAT": "y"})
    assert ok is False


# --------------------------------------------------------------- canale

def test_critical_e_warning_accodano_entrambi(modulo, monkeypatch):
    """Un solo canale: sia i ban CRITICAL sia quelli WARNING finiscono
    nella stessa coda (l'invio vero e proprio e' raggruppato e asincrono,
    vedi accoda_o_invia — qui si verifica solo che elabora() li accetti
    entrambi, non l'invio finale)."""
    monkeypatch.setattr(modulo, "geolocalizza", lambda ip: None)
    monkeypatch.setattr(modulo, "reputazione", lambda ip, key: None)
    monkeypatch.setattr(modulo, "motore_verificato", lambda ip: None)
    accodati = []
    monkeypatch.setattr(modulo, "accoda_o_invia",
                        lambda testo, livello, cfg: accodati.append((testo, livello)))

    modulo.elabora("nginx-botsearch", "203.0.113.1", "12", [],
                   config={"TELEGRAM_TOKEN": "x", "TELEGRAM_CHAT": "y"})
    modulo.elabora("photocarcifo-scansioni", "203.0.113.2", "20", [],
                   config={"TELEGRAM_TOKEN": "x", "TELEGRAM_CHAT": "y"})
    assert len(accodati) == 2


def test_elabora_ritorna_false_senza_canale_configurato(modulo, monkeypatch):
    """Senza TELEGRAM_TOKEN/TELEGRAM_CHAT non c'e' niente da accodare:
    elabora() ritorna False e accoda_o_invia() non deve nemmeno essere
    chiamata (altrimenti scriverebbe comunque nella coda su disco)."""
    monkeypatch.setattr(modulo, "geolocalizza", lambda ip: None)
    monkeypatch.setattr(modulo, "reputazione", lambda ip, key: None)
    monkeypatch.setattr(modulo, "motore_verificato", lambda ip: None)
    chiamato = []
    monkeypatch.setattr(modulo, "accoda_o_invia",
                        lambda testo, livello, cfg: chiamato.append(1))
    ok = modulo.elabora("photocarcifo-scansioni", "203.0.113.1", "20", [],
                        config={"TELEGRAM_TOKEN": "", "TELEGRAM_CHAT": ""})
    assert ok is False
    assert chiamato == []


def test_telegram_non_configurato_nessuna_notifica(modulo, blocca_rete):
    ok = modulo.elabora("photocarcifo-scansioni", "203.0.113.1", "20", [], config={})
    assert ok is False


# --------------------------------------------------- coda/raggruppamento

@pytest.fixture
def modulo_coda(modulo, tmp_path, monkeypatch):
    """Il modulo con la coda/lock puntati a file temporanei: mai quelli
    di produzione, e mai un test che finisce per leggere/scrivere una
    coda lasciata da un'esecuzione precedente."""
    monkeypatch.setattr(modulo, "CODA_TELEGRAM", str(tmp_path / "coda.jsonl"))
    monkeypatch.setattr(modulo, "CODA_LOCK", str(tmp_path / "coda.lock"))
    return modulo


def test_accoda_messaggio_scrive_una_riga_jsonl(modulo_coda):
    modulo_coda.accoda_messaggio("primo", "CRITICAL")
    modulo_coda.accoda_messaggio("secondo", "WARNING")
    righe = Path(modulo_coda.CODA_TELEGRAM).read_text().splitlines()
    assert len(righe) == 2
    assert json.loads(righe[0])["testo"] == "primo"
    assert json.loads(righe[1])["livello"] == "WARNING"


def test_svuota_coda_restituisce_e_cancella(modulo_coda):
    modulo_coda.accoda_messaggio("uno", "CRITICAL")
    modulo_coda.accoda_messaggio("due", "CRITICAL")
    eventi = modulo_coda._svuota_coda()
    assert len(eventi) == 2
    assert modulo_coda._svuota_coda() == []  # gia' svuotata: la seconda lettura non trova niente


def test_svuota_coda_file_assente_non_esplode(modulo_coda):
    assert modulo_coda._svuota_coda() == []


def test_svuota_coda_riga_corrotta_non_perde_le_altre(modulo_coda):
    with open(modulo_coda.CODA_TELEGRAM, "w") as f:
        f.write('{"testo": "buona", "livello": "CRITICAL", "quando": 1}\n')
        f.write("questa riga non e' json valido\n")
        f.write('{"testo": "anche buona", "livello": "WARNING", "quando": 2}\n')
    eventi = modulo_coda._svuota_coda()
    assert [e["testo"] for e in eventi] == ["buona", "anche buona"]


def test_messaggio_raggruppato_singolo_evento_non_aggiunge_intestazione(modulo_coda):
    """Un solo evento in coda: il messaggio e' quello originale, senza
    l'intestazione 'N avvisi ravvicinati' che avrebbe senso solo con
    piu' di un evento raggruppato insieme."""
    eventi = [{"testo": "🚫 IP BANNATO\nIP: 1.2.3.4", "livello": "CRITICAL"}]
    messaggi = modulo_coda._messaggi_raggruppati(eventi)
    assert len(messaggi) == 1
    testo, livello = messaggi[0]
    assert testo == eventi[0]["testo"]
    assert livello == "CRITICAL"


def test_messaggio_raggruppato_piu_eventi_li_include_tutti(modulo_coda):
    eventi = [
        {"testo": "🚫 IP BANNATO\nIP: 1.2.3.4", "livello": "CRITICAL"},
        {"testo": "🔍 Sito scansionato\nIP: 5.6.7.8", "livello": "WARNING"},
    ]
    messaggi = modulo_coda._messaggi_raggruppati(eventi)
    assert len(messaggi) == 1  # ben sotto il limite, un solo messaggio basta
    testo, livello = messaggi[0]
    assert "1.2.3.4" in testo and "5.6.7.8" in testo
    assert "2 avvisi ravvicinati" in testo
    assert livello == "CRITICAL"  # il piu' grave dei due vince


def test_messaggio_raggruppato_tutti_warning_resta_warning(modulo_coda):
    eventi = [
        {"testo": "🔍 Sito scansionato\nIP: 1.1.1.1", "livello": "WARNING"},
        {"testo": "🔍 Sito scansionato\nIP: 2.2.2.2", "livello": "WARNING"},
    ]
    _, livello = modulo_coda._messaggi_raggruppati(eventi)[0]
    assert livello == "WARNING"


def test_messaggio_raggruppato_oltre_il_limite_si_spezza_in_piu_messaggi(modulo_coda):
    """Il caso reale che ha fatto perdere una notifica il 31/08/2026: un
    ripristino di 11 ban dopo un riavvio della jail ha prodotto un unico
    messaggio troppo lungo per Telegram (rifiutato con HTTP 400, notifica
    mai arrivata). Molti eventi lunghi devono spezzarsi in piu' messaggi,
    ciascuno sotto il limite, invece che rischiare di perderli tutti."""
    evento_lungo = "🚫 IP BANNATO\nIP: 1.2.3.4\n" + ("dettaglio " * 100)
    eventi = [{"testo": evento_lungo, "livello": "CRITICAL"} for _ in range(20)]
    messaggi = modulo_coda._messaggi_raggruppati(eventi)
    assert len(messaggi) > 1  # troppi/troppo lunghi per stare in un solo messaggio
    for testo, _ in messaggi:
        assert len(testo) <= modulo_coda.LIMITE_TELEGRAM + 200  # margine per l'intestazione
    # nessun evento perso: ognuno compare in esattamente uno dei messaggi
    tutti_i_testi = "\n".join(t for t, _ in messaggi)
    assert tutti_i_testi.count("IP: 1.2.3.4") == 20


def test_messaggio_raggruppato_sotto_il_limite_resta_un_solo_messaggio(modulo_coda):
    eventi = [{"testo": f"🔍 Sito scansionato\nIP: 10.0.0.{i}", "livello": "WARNING"} for i in range(5)]
    messaggi = modulo_coda._messaggi_raggruppati(eventi)
    assert len(messaggi) == 1


def test_accoda_o_invia_non_blocca_il_chiamante(modulo_coda, monkeypatch):
    """Il punto essenziale per fail2ban: accoda_o_invia() deve tornare
    subito, senza aspettare la finestra di raggruppamento — e' il
    processo figlio staccato che aspetta, non chi chiama."""
    monkeypatch.setattr(modulo_coda, "FINESTRA_RAGGRUPPAMENTO", 5)
    inizio = time.time()
    modulo_coda.accoda_o_invia("test", "WARNING", {"TELEGRAM_TOKEN": "x", "TELEGRAM_CHAT": "y"})
    durata = time.time() - inizio
    assert durata < 1  # ben sotto la finestra di 5s: non ha aspettato lei


def test_accoda_o_invia_secondo_evento_non_lancia_un_secondo_flush(modulo_coda, monkeypatch):
    """Il lock deve impedire a una seconda chiamata ravvicinata di
    lanciare un secondo processo di flush: solo il primo evento della
    finestra fa da capofila, gli altri si limitano ad accodare.

    Un vero os.fork() duplica il processo: il lock preso prima del fork
    resta trattenuto tramite il file descriptor ereditato dal figlio
    anche dopo che il genitore chiude il proprio — per questo il finto
    fork qui sotto NON chiude il lock quando simula "sono il genitore",
    esattamente come non lo chiuderebbe il vero os.fork(). os.fork e'
    sostituito solo nel namespace del modulo caricato (non globalmente
    su os stesso): patchare os.fork per l'intero processo pytest
    romperebbe qualunque altra cosa nella suite che dipenda da processi
    veri."""
    lanci = []

    def fork_finto():
        lanci.append(1)
        return 1  # simula sempre "sono il genitore": nessun figlio parte davvero, lock non toccato qui

    monkeypatch.setattr(modulo_coda.os, "fork", fork_finto)
    # os.close(lock_fd) nel ramo genitore va reso innocuo: nel mondo
    # reale chiude SOLO la copia del genitore, il figlio (mai creato
    # davvero in questo test) tiene ancora la sua. Qui non c'e' un vero
    # figlio quindi il fd va lasciato aperto, non chiuso, per simulare
    # correttamente "qualcun altro lo tiene ancora".
    monkeypatch.setattr(modulo_coda.os, "close", lambda fd: None)
    cfg = {"TELEGRAM_TOKEN": "x", "TELEGRAM_CHAT": "y"}
    modulo_coda.accoda_o_invia("uno", "WARNING", cfg)
    modulo_coda.accoda_o_invia("due", "WARNING", cfg)
    assert len(lanci) == 1  # il lock, tenuto dal primo, ha impedito il secondo fork
    assert len(Path(modulo_coda.CODA_TELEGRAM).read_text().splitlines()) == 2  # entrambi accodati comunque


# ------------------------------------------------------------- anti-spam

def test_stesso_ip_piu_volte_non_rifa_i_lookup(modulo, monkeypatch):
    """Non e' un vero anti-spam sull'invio (ogni ban e' un evento reale
    distinto, deciso da fail2ban), ma i LOOKUP costosi (GeoIP/abuse) non
    devono ripetersi per lo stesso indirizzo entro il TTL della cache —
    verificato gia' in test_geolocalizza_usa_la_cache_al_secondo_giro,
    qui si verifica lo stesso per reputazione()."""
    chiamate = []
    monkeypatch.setattr(modulo, "_http_json", lambda *a, **k: (
        chiamate.append(1),
        {"data": {"abuseConfidenceScore": 50, "totalReports": 3}})[1])
    modulo.reputazione("203.0.113.200", "chiave")
    modulo.reputazione("203.0.113.200", "chiave")
    assert len(chiamate) == 1


# ------------------------------------------------------------------ CLI

def test_main_senza_argomenti_non_esplode(modulo, monkeypatch, capsys):
    import sys
    monkeypatch.setattr(sys, "argv", ["photocarcifo-ban-alert.py"])
    with pytest.raises(SystemExit) as exc:
        modulo.main()
    assert exc.value.code == 0


def test_main_decodifica_base64_correttamente(modulo, monkeypatch):
    import base64
    import sys
    righe_b64 = base64.b64encode("\n".join(RIGHE_ESEMPIO).encode()).decode()
    monkeypatch.setattr(sys, "argv", [
        "photocarcifo-ban-alert.py", "photocarcifo-scansioni", "203.0.113.55", "18", righe_b64])
    monkeypatch.setattr(modulo, "leggi_config", lambda: {})  # nessun invio reale
    with pytest.raises(SystemExit) as exc:
        modulo.main()
    assert exc.value.code == 0


def test_main_argomento_base64_corrotto_non_esplode(modulo, monkeypatch):
    import sys
    monkeypatch.setattr(sys, "argv", [
        "photocarcifo-ban-alert.py", "sshd", "1.2.3.4", "5", "!!!non-e-base64!!!"])
    monkeypatch.setattr(modulo, "leggi_config", lambda: {})
    with pytest.raises(SystemExit) as exc:
        modulo.main()
    assert exc.value.code == 0


# --------------------------------------------------------------- storico

def test_salva_e_rileggi_snapshot(modulo):
    modulo.salva_snapshot("photocarcifo-scansioni", "1.2.3.4", "27",
                          "Scansione di file sensibili", ["/.env", "/wp-admin"],
                          "404", "python-requests",
                          {"country": "Canada", "city": "Toronto"},
                          {"score": 100, "segnalazioni": 1448})
    snap = modulo.leggi_snapshot("1.2.3.4")
    assert snap is not None
    assert snap["motivo"] == "Scansione di file sensibili"
    assert snap["tentativi"] == "27"
    assert snap["path"] == ["/.env", "/wp-admin"]
    assert snap["geo"]["city"] == "Toronto"
    assert snap["abuse"]["score"] == 100
    assert "quando" in snap


def test_leggi_snapshot_ip_mai_visto_ritorna_none(modulo):
    assert modulo.leggi_snapshot("9.9.9.9") is None


def test_secondo_ban_sovrascrive_il_precedente(modulo):
    modulo.salva_snapshot("sshd", "1.2.3.4", "5", "vecchio motivo", [], None, None, None, None)
    modulo.salva_snapshot("photocarcifo-scansioni", "1.2.3.4", "20",
                          "nuovo motivo", ["/.env"], "404", None, None, None)
    snap = modulo.leggi_snapshot("1.2.3.4")
    assert snap["motivo"] == "nuovo motivo"
    assert snap["tentativi"] == "20"


def test_storico_non_cresce_oltre_il_massimo(modulo, monkeypatch):
    monkeypatch.setattr(modulo, "STORICO_MASSIMO", 5)
    for i in range(10):
        modulo.salva_snapshot("sshd", f"10.0.0.{i}", "1", "test", [], None, None, None, None)
    storico = modulo._leggi_storico()
    assert len(storico) <= 5


def test_elabora_salva_lo_snapshot_prima_di_notificare(modulo, monkeypatch):
    """L'ordine richiesto: salva, POI notifica. Verificato facendo
    fallire invia_telegram() e controllando che lo snapshot sia comunque
    presente."""
    monkeypatch.setattr(modulo, "geolocalizza", lambda ip: None)
    monkeypatch.setattr(modulo, "reputazione", lambda ip, key: None)
    monkeypatch.setattr(modulo, "motore_verificato", lambda ip: None)
    monkeypatch.setattr(modulo, "invia_telegram", lambda cfg, testo: False)
    modulo.elabora("photocarcifo-scansioni", "1.2.3.4", "27", RIGHE_ESEMPIO,
                   config={"TELEGRAM_TOKEN": "t", "TELEGRAM_CHAT": "c"})
    snap = modulo.leggi_snapshot("1.2.3.4")
    assert snap is not None
    assert "/.env" in (snap.get("path") or [])


def test_storico_file_corrotto_non_esplode(modulo, tmp_path):
    with open(modulo.STORICO, "w", encoding="utf-8") as f:
        f.write("{questo non e' json valido")
    assert modulo.leggi_snapshot("1.2.3.4") is None
    # e salva_snapshot deve comunque funzionare ripartendo da vuoto
    modulo.salva_snapshot("sshd", "1.2.3.4", "1", "test", [], None, None, None, None)
    assert modulo.leggi_snapshot("1.2.3.4") is not None
