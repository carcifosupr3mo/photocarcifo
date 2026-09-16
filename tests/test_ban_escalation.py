"""L'escalation da "vedi la pagina di blocco" a "il firewall ti rifiuta".

La parte che decide vive in nginx e in fail2ban, non in Python: qui si
tengono ferme le due cose che, cambiate per sbaglio, la romperebbero in
silenzio — la selezione di cosa finisce nel registro dei sondaggi (una
riga sbagliata nelle map e la pagina di blocco ricaricata porterebbe al
firewall una persona che non ha fatto niente) e il fatto che /unbanip
tolga il ban da TUTTE le jail e non solo dalla prima trovata.

Il comportamento vero e' stato verificato sul sistema, con un indirizzo di
documentazione legato al loopback: navigazione normale che resta sulla
pagina, venticinque ricariche di /bloccato che non contano, trenta
miniature che non contano, venticinque indirizzi sospetti che portano al
blocco nel firewall, connessione poi rifiutata, /unbanip che rimette tutto
a posto. Quello che segue protegge quel comportamento dalle modifiche
future.
"""
import re
from pathlib import Path

import pytest

from test_bot_telegram import _carica_modulo

RADICE = Path(__file__).resolve().parent.parent
SNIPPET = RADICE / "config" / "nginx" / "snippets" / "photocarcifo-bloccati.conf"
SITO = RADICE / "config" / "nginx" / "photocarcifo.conf"


# ------------------------------------------------ il segnale nei registri


def _voci_innocue():
    """Le righe vere della map, senza i commenti: un commento che nomina
    /static/ non e' una regola, e confonderlo con una ha gia' fatto
    passare un test che non provava niente."""
    testo = SNIPPET.read_text(encoding="utf-8")
    blocco = testo[testo.index("map $uri $pc_uri_innocuo"):]
    blocco = blocco[:blocco.index("\n}")]
    return [r.strip() for r in blocco.splitlines()
            if r.strip().endswith("1;") and not r.strip().startswith("#")]


def test_esiste_un_registro_dedicato_ai_soli_bloccati():
    """Non si contano i 302 del registro normale: di 302 legittimi ce ne
    sono (www -> canonico, http -> https, redirect dell'applicazione), e
    contarli tutti vorrebbe dire cacciare qualcuno per un redirect."""
    testo = SITO.read_text(encoding="utf-8")
    assert "photocarcifo-bloccati.log" in testo
    assert "if=$pc_sondaggio" in testo, (
        "il registro dei sondaggi deve essere condizionato a $pc_sondaggio")


def _regole_innocue():
    """Le regole della map, tradotte in qualcosa che si puo' eseguire.

    I test di prima cercavano sottostringhe nel file e restavano verdi
    anche togliendo l'ancoraggio a una regex — cioe' proprio il difetto
    che dicevano di impedire. Qui le regole si valutano davvero, come fa
    nginx: le voci letterali sono confronti esatti, quelle con ~ sono
    espressioni regolari."""
    regole = []
    for voce in _voci_innocue():
        chiave = voce.split()[0].strip('"')
        if chiave.startswith("~"):
            regole.append(("regex", re.compile(chiave[1:])))
        else:
            regole.append(("uguale", chiave))
    return regole


def _innocuo(uri, regole=None):
    """Come deciderebbe nginx per questo indirizzo."""
    for tipo, regola in (regole or _regole_innocue()):
        if tipo == "uguale" and uri == regola:
            return True
        if tipo == "regex" and regola.search(uri):
            return True
    return False


# Gli indirizzi che una persona chiede davvero usando il sito: nessuno di
# questi deve contare come sondaggio, altrimenti si finisce col bloccare
# nel firewall una cliente che sceglie le foto o venti persone dietro lo
# stesso indirizzo condiviso.
INNOCUI = [
    "/", "/en/", "/fr/", "/de/", "/es/",
    "/radunimoto", "/en/radunimoto", "/contattami", "/chi-sono",
    "/novita", "/recensioni", "/privacy", "/search", "/novita.xml",
    "/mie-preferite", "/en/mie-preferite",
    "/n/raduno-zona-industriale-castione-06-09-2026", "/en/n/bmx",
    "/p/aKJ1wf46_AykpN4fUkn_QA", "/f/KKV7M0o76dwgStbMYI9ivw",
    "/fs/s3pxzKoBsMGvPAR5MTa99g", "/fs/s3pxzKoBsMGvPAR5MTa99g/zip",
    "/f/KKV7M0o76dwgStbMYI9ivw/miniatura",
    "/preferiti/50629", "/preferiti/album/24210", "/preferiti-nome",
    "/condividi/50629", "/condividi/selezione", "/lingua/en",
    "/download/50629", "/video/12", "/zip/select", "/zip/node/24210",
    "/thumb/50629", "/thumb2x/1", "/preview/7", "/cover/3", "/social/9",
    "/static/js/app.js", "/static/css/style.css", "/static/errori/429.html",
    "/favicon.ico", "/apple-touch-icon.png", "/robots.txt",
    "/sitemap.xml", "/sitemap-immagini.xml", "/sitemap-immagini-2.xml",
    "/bloccato", "/bloccato-pagina.html",
    "/.well-known/acme-challenge/qualcosa",
]

# Gli indirizzi che il sito non ha: questi devono contare, altrimenti un
# programma gia' bloccato puo' sondare per sempre senza che nessuno se ne
# accorga — che e' il buco che tutto questo lavoro chiude.
SONDAGGI = [
    "/.env", "/wp-config.php", "/wp-login.php", "/.git/config",
    "/phpmyadmin", "/.aws/credentials", "/id_rsa", "/shell.php",
    "/actuator/env", "/server-status", "/.htpasswd", "/vendor/phpunit",
    # I casi che passavano nascondendosi dietro un prefisso buono:
    "/static/.env", "/thumb/id_rsa", "/media/wp-config.php", "/file/.env",
    "/sitemap.php", "/preferiti.php", "/condividi.aspx",
    "/download/.env", "/zip/../etc/passwd",
    "/admin", "/admin/login",
]


@pytest.mark.parametrize("uri", INNOCUI)
def test_gli_indirizzi_veri_del_sito_non_contano(uri):
    assert _innocuo(uri), (
        f"{uri} verrebbe contato come sondaggio: una persona che usa il "
        f"sito normalmente rischia il blocco nel firewall")


@pytest.mark.parametrize("uri", SONDAGGI)
def test_gli_indirizzi_che_il_sito_non_ha_contano(uri):
    assert not _innocuo(uri), (
        f"{uri} passa per innocuo: un sondaggio puo' nascondersi li' e "
        f"non far scattare mai l'escalation")


def test_le_lingue_della_map_sono_quelle_vere_del_sito():
    """La lista en|fr|de|es e' copiata a mano nella configurazione di
    nginx. Aggiungendo una sesta lingua all'applicazione senza toccare
    nginx, ogni pagina tradotta diventerebbe di colpo un "sondaggio" — e
    chi la visita finirebbe nel firewall, in silenzio."""
    import sys
    sys.path.insert(0, str(RADICE))
    from app.lingue import PREFISSI

    regole = _regole_innocue()
    for lingua in PREFISSI:
        assert _innocuo(f"/{lingua}/radunimoto", regole), (
            f"la lingua {lingua} esiste nell'applicazione ma per nginx "
            f"non e' un indirizzo del sito")


# Rotte pubbliche che si e' scelto di lasciare contate, con il motivo.
# Stanno scritte qui e non nascoste in una regex, cosi' la scelta si vede.
DELIBERATAMENTE_CONTATE = {
    # La radice del montaggio: gli asset veri sono /static/qualcosa e sono
    # coperti. /static nudo non lo chiede nessun browser.
    "/static",
    # Vecchia galleria, ancora nell'indice di Google. Sono anche due voci
    # classiche degli elenchi usati dagli scanner: chi ha un segnalibro
    # vecchio fa una richiesta, non venti, e non arriva mai alla soglia.
    "/index.php", "/picture.php",
    # Lo chiama solo il controllo automatico da 127.0.0.1, che non puo'
    # essere bloccato (gli indirizzi interni non entrano nell'elenco).
    # Da fuori, chiederlo e' un sondaggio come un altro.
    "/healthz",
}


def test_ogni_rotta_pubblica_dell_app_non_conta():
    """Legame diretto con l'applicazione: se domani nasce una rotta
    pubblica nuova e nessuno tocca nginx, chi la usa da bloccato viene
    contato. Le rotte sotto /admin restano fuori: quelle e' giusto
    contarle."""
    import sys
    sys.path.insert(0, str(RADICE))
    from app.main import app

    regole = _regole_innocue()
    scoperte = []
    for rotta in app.routes:
        percorso = getattr(rotta, "path", "")
        if not percorso.startswith("/") or percorso.startswith("/admin"):
            continue
        # I segnaposto si riempiono con qualcosa di plausibile.
        esempio = (percorso
                   .replace("{media_id}", "42").replace("{node_id}", "42")
                   .replace("{token}", "aKJ1wf46_AykpN4fUkn").replace("{slug}", "album")
                   .replace("{codice}", "en").replace("{id}", "42")
                   .replace("{numero}", "2").replace("{lingua}", "en"))
        if "{" in esempio:
            continue  # segnaposto che non so riempire: non invento
        if esempio in DELIBERATAMENTE_CONTATE:
            continue
        if not _innocuo(esempio, regole):
            scoperte.append(f"{percorso} (es. {esempio})")
    assert not scoperte, (
        "rotte pubbliche che verrebbero contate come sondaggio (se sono "
        "volute, vanno in DELIBERATAMENTE_CONTATE con il motivo):\n  "
        + "\n  ".join(scoperte))


# ------------------------------------------------------- /unbanip totale


class _Fail2banFinto:
    """Risponde come fail2ban-client, e sa anche non rispondere.

    mute: jail il cui "status" fallisce (ferma, non caricata, lenta).
    unban_falliti: jail in cui l'unban non riesce.
    Servono per i due casi che contano davvero — quelli in cui il comando
    potrebbe dire di aver fatto una cosa che non ha fatto."""

    def __init__(self, jail_a_ip, mute=(), unban_falliti=()):
        self.jail_a_ip = {k: list(v) for k, v in jail_a_ip.items()}
        self.mute = set(mute)
        self.unban_falliti = set(unban_falliti)
        self.sbloccati = []

    def __call__(self, argomenti, secondi=120):
        if argomenti[:2] == ["fail2ban-client", "status"] and len(argomenti) > 2:
            jail = argomenti[2]
            if jail in self.mute:
                return "(non riuscito: [Errno 2] No such file or directory)"
            ips = self.jail_a_ip.get(jail, [])
            return f"Banned IP list:\t{' '.join(ips)}" if ips else "Banned IP list:\t"
        if len(argomenti) > 4 and argomenti[3] == "unbanip":
            jail, ip = argomenti[2], argomenti[4]
            self.sbloccati.append((jail, ip))
            if jail in self.unban_falliti:
                return "0"
            if ip in self.jail_a_ip.get(jail, []):
                self.jail_a_ip[jail].remove(ip)
        return "1"


@pytest.fixture
def bot(monkeypatch, tmp_path):
    modulo = _carica_modulo()
    monkeypatch.setattr(modulo, "tg", lambda *a, **k: {"ok": True, "result": {}})
    monkeypatch.setattr(modulo, "LOG", str(tmp_path / "bot.log"))
    modulo._attesa.clear()
    modulo._in_corso = None
    modulo._ULTIMO_RESPINTO.clear()
    return modulo


def test_unbanip_toglie_da_tutte_le_jail_non_solo_dalla_prima(bot, monkeypatch):
    """Il punto piu' importante di tutto il lavoro sull'escalation: chi ha
    insistito sta in due jail insieme — quella che l'ha bloccato con la
    pagina e quella che l'ha messo nel firewall. Togliendolo da una sola
    resterebbe fuori lo stesso, con un messaggio che dice il contrario."""
    finto = _Fail2banFinto({
        "photocarcifo-manuale": ["8.8.8.8"],
        "photocarcifo-ban-escalation": ["8.8.8.8"],
    })
    monkeypatch.setattr(bot, "esegui", finto)
    risposta = bot.cmd_unbanip("8.8.8.8")
    assert "sbloccato" in risposta
    assert set(finto.sbloccati) == {
        ("photocarcifo-manuale", "8.8.8.8"),
        ("photocarcifo-ban-escalation", "8.8.8.8"),
    }
    # e lo dice, cosi' chi legge sa che il firewall e' stato tolto davvero
    assert "photocarcifo-ban-escalation" in risposta


def test_la_jail_di_escalation_e_fra_quelle_che_il_bot_guarda(bot):
    """Se non fosse in CARCERI: /bloccati non la mostrerebbe, /sblocca non
    la libererebbe e — soprattutto — /unbanip non saprebbe nemmeno di
    doverci guardare."""
    assert "photocarcifo-ban-escalation" in bot.CARCERI


def test_unbanip_non_tocca_i_ban_ssh(bot, monkeypatch):
    """Sbloccare un indirizzo dal sito e' una cosa; riaprirgli la porta di
    casa perche' per caso stava tentando anche le password SSH e' un'altra.
    Scenario reale: arriva l'avviso dell'escalation, si riconosce
    l'indirizzo dell'ufficio e si digita /unbanip credendo di togliere un
    blocco della galleria — non deve riaprire SSH a chi stava provando le
    password."""
    finto = _Fail2banFinto({"sshd": ["8.8.8.8"]})
    monkeypatch.setattr(bot, "esegui", finto)
    risposta = bot.cmd_unbanip("8.8.8.8")
    assert finto.sbloccati == [], "sshd non deve essere toccato"
    assert "non risulta bloccato" in risposta
    assert "sshd" not in bot.CARCERI_SITO


def test_ipv6_scritto_in_modo_diverso_viene_riconosciuto(bot, monkeypatch):
    """2001:db8:0:0::1 e 2001:db8::1 sono lo stesso indirizzo: confrontarli
    come testo faceva risultare libero un IPv6 che era bloccato."""
    finto = _Fail2banFinto({"photocarcifo-manuale": ["2001:db8::1"]})
    monkeypatch.setattr(bot, "esegui", finto)
    risposta = bot.cmd_unbanip("2001:db8:0:0::1")
    assert "sbloccato" in risposta
    # si passa a fail2ban la forma con cui LUI l'ha memorizzato
    assert finto.sbloccati == [("photocarcifo-manuale", "2001:db8::1")]


def test_unbanip_dice_sempre_da_dove_ha_tolto_il_ban(bot, monkeypatch):
    """Anche con una jail sola: chi legge deve sapere cosa ha appena
    tolto, non fidarsi di una spunta verde."""
    finto = _Fail2banFinto({"photocarcifo-login": ["8.8.8.8"]})
    monkeypatch.setattr(bot, "esegui", finto)
    risposta = bot.cmd_unbanip("8.8.8.8")
    assert "photocarcifo-login" in risposta


def test_una_jail_che_non_risponde_non_viene_scambiata_per_vuota(bot, monkeypatch):
    """Lo scenario per cui il comando esiste: arriva l'avviso
    dell'escalation, si sblocca dal telefono, si crede fatto. Se la jail
    del firewall non risponde, il ban e' ancora li' — e dire "non risulta
    bloccato" sarebbe la bugia peggiore possibile."""
    finto = _Fail2banFinto({}, mute=["photocarcifo-ban-escalation"])
    monkeypatch.setattr(bot, "esegui", finto)
    risposta = bot.cmd_unbanip("8.8.8.8")
    assert "non risulta bloccato" not in risposta
    assert "photocarcifo-ban-escalation" in risposta
    assert finto.sbloccati == []


def test_un_unban_fallito_non_diventa_una_spunta_verde(bot, monkeypatch):
    finto = _Fail2banFinto(
        {"photocarcifo-manuale": ["8.8.8.8"],
         "photocarcifo-ban-escalation": ["8.8.8.8"]},
        unban_falliti=["photocarcifo-ban-escalation"])
    monkeypatch.setattr(bot, "esegui", finto)
    risposta = bot.cmd_unbanip("8.8.8.8")
    assert "sblocco parziale" in risposta
    assert "NON riuscito" in risposta
    assert "photocarcifo-ban-escalation" in risposta


def test_un_ban_di_sottorete_viene_riconosciuto(bot, monkeypatch):
    """fail2ban accetta anche i ban di sottorete: saltarli in silenzio
    faceva dire "non risulta bloccato" a un indirizzo che era bloccato."""
    finto = _Fail2banFinto({"photocarcifo-login": ["8.8.8.0/24"]})
    monkeypatch.setattr(bot, "esegui", finto)
    risposta = bot.cmd_unbanip("8.8.8.8")
    assert "sbloccato" in risposta
    assert finto.sbloccati == [("photocarcifo-login", "8.8.8.0/24")]
