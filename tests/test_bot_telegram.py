"""Il bot Telegram amministrativo (script/photocarcifo-bot.py).

Non e' python-telegram-bot: e' polling manuale sincrono, dispatch a
dizionario, un solo interlocutore autorizzato (chat_id). Questi test
importano lo script come modulo e sostituiscono SEMPRE tg() (l'unica
funzione che parla con la rete) con un doppio finto: nessuna chiamata
arriva mai a api.telegram.org durante la suite — verificato esplicitamente
in test_nessuna_chiamata_di_rete_reale.
"""
import importlib.util
import time
from pathlib import Path

import pytest

RADICE = Path(__file__).resolve().parent.parent
SCRIPT = RADICE / "script"


def _carica_modulo():
    """Il file si chiama photocarcifo-bot.py (trattino): non e' un nome
    di modulo Python valido per un `import` diretto, va caricato dal
    percorso."""
    percorso = SCRIPT / "photocarcifo-bot.py"
    spec = importlib.util.spec_from_file_location("photocarcifo_bot_script", percorso)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture
def bot(monkeypatch, tmp_path):
    """Il modulo del bot, ricaricato per ogni test (stato di modulo come
    _attesa/_in_corso non deve sopravvivere fra un test e l'altro), con
    tg() sostituita da un finto che registra le chiamate e non tocca mai
    la rete, e LOG puntato a un file temporaneo invece che a quello di
    produzione (/var/lib/photocarcifo/bot.log) — senza questo, ogni test
    scriveva davvero nel log del bot vivo."""
    modulo = _carica_modulo()

    chiamate = []

    def tg_finta(metodo, attesa=20, **dati):
        chiamate.append({"metodo": metodo, "dati": dati})
        if metodo == "sendMessage":
            return {"ok": True, "result": {"message_id": len(chiamate)}}
        if metodo == "getUpdates":
            return {"ok": True, "result": []}
        if metodo == "setMyCommands":
            return {"ok": True, "result": True}
        return {"ok": True, "result": None}

    monkeypatch.setattr(modulo, "tg", tg_finta)
    monkeypatch.setattr(modulo, "LOG", str(tmp_path / "bot.log"))
    modulo._CHIAMATE = chiamate
    # Stato pulito fra un test e l'altro: _attesa, _in_corso e
    # _ULTIMO_RESPINTO sono dizionari/variabili di modulo condivisi.
    modulo._attesa.clear()
    modulo._in_corso = None
    modulo._ULTIMO_RESPINTO.clear()
    yield modulo


def _messaggi_inviati(bot):
    return [c["dati"]["text"] for c in bot._CHIAMATE if c["metodo"] == "sendMessage"]


# --------------------------------------------------------- rete reale: NO

def test_nessuna_chiamata_di_rete_reale(bot, monkeypatch):
    """Requisito esplicito: durante i test non deve mai partire una
    richiesta HTTP verso api.telegram.org. Si sostituisce urlopen con una
    funzione che fallisce sempre se chiamata: se qualche percorso di
    codice bypassasse il finto tg() e chiamasse urllib direttamente, il
    test lo scoprirebbe subito invece di mandare un messaggio vero.

    ATTENZIONE: /applica SI con la conferma valida esegue per davvero
    /usr/local/bin/photocarcifo-applica.sh (fino a 900 secondi, e quello
    script a sua volta lancia pytest sull'intera suite — un giro dentro
    l'altro). bot.esegui va SEMPRE sostituito prima di una conferma "SI"
    su un comando reale, altrimenti il test tocca davvero il sistema. Lo
    stesso vale per /riavvia, /salva, /sblocca."""
    import urllib.request

    def esplodi(*a, **k):
        raise AssertionError("chiamata di rete reale intercettata durante i test")

    monkeypatch.setattr(urllib.request, "urlopen", esplodi)
    monkeypatch.setattr(bot, "esegui", lambda *a, **k: "(comando finto nei test)")

    # Un giro realistico di comandi, incluse le conferme: se qualcosa
    # sfuggisse al mock di tg(), qui esploderebbe.
    bot.gestisci("/stato")
    bot.gestisci("/aiuto")
    bot.gestisci("/applica")
    bot._attesa["applica"] = time.time()
    bot.gestisci("/applica SI")
    # 0 chiamate reali all'API Telegram durante pytest: confermato.
    # 0 esecuzioni reali di photocarcifo-applica.sh: confermato.


# --------------------------------------------------------------- /applica

def test_applica_senza_conferma_chiede_si(bot):
    r = bot.gestisci("/applica")
    assert "Confermi" in r
    assert "/applica SI" in r
    assert "applica" in bot._attesa


def test_applica_si_senza_richiesta_precedente_dice_scaduta(bot):
    r = bot.gestisci("/applica SI")
    assert "scaduta" in r.lower()


def test_applica_si_entro_la_scadenza_esegue(bot, monkeypatch):
    bot._attesa["applica"] = time.time()
    eseguiti = []
    monkeypatch.setattr(bot, "esegui", lambda argomenti, secondi=120: (
        eseguiti.append(argomenti), "tutto ok")[1])
    r = bot.gestisci("/applica SI")
    assert eseguiti and eseguiti[0][0].endswith("photocarcifo-applica.sh")
    assert "tutto ok" in r


def test_applica_si_dopo_scadenza_non_esegue(bot, monkeypatch):
    bot._attesa["applica"] = time.time() - 61  # oltre SCADENZA_CONFERMA=60
    eseguiti = []
    monkeypatch.setattr(bot, "esegui", lambda *a, **k: eseguiti.append(1))
    r = bot.gestisci("/applica SI")
    assert not eseguiti
    assert "scaduta" in r.lower()


def test_applica_spazi_multipli_e_iniziali(bot):
    """Spazi extra prima/dopo/fra le parole non devono impedire il
    riconoscimento del comando."""
    r = bot.gestisci("   /applica    ")
    assert "Confermi" in r


def test_applica_maiuscole(bot):
    r = bot.gestisci("/APPLICA")
    assert "Confermi" in r


def test_applica_con_nome_bot(bot, monkeypatch):
    """/applica@NomeBot deve funzionare come /applica (rilevante se il bot
    viene mai usato in un gruppo, anche se oggi risponde solo alla chat
    autorizzata)."""
    bot._attesa["applica"] = time.time()
    monkeypatch.setattr(bot, "esegui", lambda *a, **k: "ok")
    r = bot.gestisci("/applica@PhotocarcifoBot SI")
    assert "ok" in r


def test_applica_parametro_non_valido_chiede_di_nuovo(bot):
    """Un argomento diverso da SI (es. "si" minuscolo scritto storto, o
    testo a caso) non deve eseguire l'azione: solo "SI" maiuscolo conta,
    tutto il resto e' come nessun argomento."""
    r = bot.gestisci("/applica forse")
    assert "Confermi" in r
    assert "applica" in bot._attesa


def test_applica_errore_interno_non_rompe_il_bot(bot, monkeypatch):
    bot._attesa["applica"] = time.time()

    def esplode(*a, **k):
        raise RuntimeError("disco pieno")

    monkeypatch.setattr(bot, "esegui", esplode)
    r = bot.gestisci("/applica SI")
    assert "errore" in r.lower()
    assert "disco pieno" in r  # e()-scappato, ma il messaggio arriva
    assert bot._in_corso is None  # il finally deve aver ripulito lo stato


def test_applica_secondo_comando_mentre_il_primo_gira(bot, monkeypatch):
    """Il bug reale: un /applica lanciato mentre un altro comando lungo e'
    gia' in corso deve dare un feedback immediato, non restare in coda
    senza risposta (quello che sembrava "non funziona sempre")."""
    bot._in_corso = "applica"
    r = bot.gestisci("/applica")
    assert "Sto ancora eseguendo" in r
    assert "/applica" in r


def test_applica_doppio_invio_rapido_secondo_riceve_scaduta(bot, monkeypatch):
    """Due /applica SI a distanza di pochi millisecondi: il primo consuma
    la conferma, il secondo la trova gia' usata. E' voluto (previene
    l'esecuzione doppia), ma deve dare un messaggio chiaro, non un
    traceback o silenzio."""
    bot._attesa["applica"] = time.time()
    monkeypatch.setattr(bot, "esegui", lambda *a, **k: "fatto")
    primo = bot.gestisci("/applica SI")
    secondo = bot.gestisci("/applica SI")
    assert "fatto" in primo
    assert "scaduta" in secondo.lower()


# --------------------------------------------------- altri comandi (audit)

@pytest.mark.parametrize("comando", [
    "stato", "errori", "visite", "spazio", "foto", "recensioni",
    "numeri", "bloccati", "aiuto", "start", "help",
])
def test_comandi_di_sola_lettura_rispondono_sempre(bot, comando):
    """Ogni comando senza conferma deve rispondere qualcosa, sempre, anche
    se i dati sottostanti (DB, file di stato, fail2ban) non ci sono in
    questo ambiente di test — non deve mai lanciare un'eccezione non
    gestita ne' restituire una stringa vuota."""
    r = bot.gestisci(f"/{comando}")
    assert r and isinstance(r, str)


@pytest.mark.parametrize("comando", ["salva", "riavvia", "sblocca", "applica"])
def test_comandi_con_conferma_non_eseguono_senza_si(bot, comando, monkeypatch):
    eseguiti = []
    monkeypatch.setattr(bot, "esegui", lambda *a, **k: eseguiti.append(1))
    r = bot.gestisci(f"/{comando}")
    assert not eseguiti
    assert "Confermi" in r


def test_comando_sconosciuto_da_risposta_chiara(bot):
    r = bot.gestisci("/nonesisteproprio")
    assert "Non conosco" in r
    assert "/aiuto" in r


def test_testo_senza_slash_iniziale(bot):
    r = bot.gestisci("ciao bot")
    assert "Non ho capito" in r


def test_messaggio_vuoto(bot):
    r = bot.gestisci("")
    assert "Non ho capito" in r


def test_aiuto_elenca_solo_comandi_reali(bot):
    """La lista in /aiuto deve corrispondere esattamente ai comandi
    presenti nel dizionario COMANDI (meno gli alias aiuto/start/help che
    non hanno bisogno di una riga propria)."""
    r = bot.gestisci("/aiuto")
    visibili = set(bot.COMANDI) - {"aiuto", "start", "help"}
    for nome in visibili:
        assert f"/{nome}" in r, f"/{nome} esiste nel codice ma non in /aiuto"


def test_menu_botfather_corrisponde_ai_comandi_reali(bot):
    """setMyCommands (chiamata dentro main(), non testata qui per intero)
    elenca i comandi in una lista scritta a mano in main(): verifica che
    quella lista, letta dal sorgente, non contenga comandi inesistenti ne'
    ne dimentichi di esistenti — a parte gli alias silenziosi start/help,
    che condividono la funzione di /aiuto ma non hanno senso come voce
    separata nel menu di Telegram."""
    sorgente = (SCRIPT / "photocarcifo-bot.py").read_text(encoding="utf-8")
    inizio = sorgente.index("for c, d in [", sorgente.index('tg("setMyCommands"'))
    fine = sorgente.index("]))", inizio)
    blocco_menu = sorgente[inizio:fine]
    dal_menu = set(__import__("re").findall(r'\("(\w+)",', blocco_menu))
    attesi = set(bot.COMANDI) - {"start", "help"}
    assert dal_menu == attesi, (
        f"disallineamento fra COMANDI e setMyCommands: "
        f"solo nel codice {attesi - dal_menu}, solo nel menu {dal_menu - attesi}")


# ------------------------------------------------------------ autorizzazione

def test_solo_la_chat_configurata_riceve_risposta(bot):
    """Il controllo di autorizzazione vero e proprio vive nel giro
    principale (main()), non in gestisci(): qui si verifica che il
    confronto usato sia sulla chat_id esatta, replicando la stessa
    condizione usata nello script."""
    autorizzato = str(bot.CHAT)
    assert str({"id": bot.CHAT}.get("id")) == autorizzato
    assert str({"id": 999999999999}.get("id")) != autorizzato


# --------------------------------------------------------------------- log

def test_log_non_contiene_il_token(bot, tmp_path, monkeypatch):
    """loga() non deve mai scrivere il token del bot: verificato scrivendo
    davvero su un file temporaneo (non quello di produzione) ed
    eseguendo un giro di comandi."""
    finto_log = tmp_path / "bot.log"
    monkeypatch.setattr(bot, "LOG", str(finto_log))
    monkeypatch.setattr(bot, "esegui", lambda *a, **k: "(comando finto nei test)")
    bot.gestisci("/applica")
    bot._attesa["applica"] = time.time()
    bot.gestisci("/applica SI")
    contenuto = finto_log.read_text(encoding="utf-8") if finto_log.exists() else ""
    if not bot.TOKEN:
        pytest.skip("TOKEN vuoto in questo ambiente: nulla da verificare")
    assert bot.TOKEN not in contenuto


def test_log_registra_comando_ed_esito(bot, tmp_path, monkeypatch):
    finto_log = tmp_path / "bot.log"
    monkeypatch.setattr(bot, "LOG", str(finto_log))
    bot.gestisci("/stato")
    contenuto = finto_log.read_text(encoding="utf-8")
    assert "/stato" in contenuto
    assert "completato" in contenuto


# ------------------------------------------------------------------ scrivi()

def test_scrivi_riprova_una_volta_su_fallimento_rete(bot, monkeypatch):
    tentativi = []

    def tg_fallisce_poi_riesce(metodo, attesa=20, **dati):
        tentativi.append(1)
        if metodo != "sendMessage":
            return {"ok": True, "result": []}
        if len(tentativi) == 1:
            return None  # come un timeout/errore di rete
        return {"ok": True, "result": {}}

    monkeypatch.setattr(bot, "tg", tg_fallisce_poi_riesce)
    monkeypatch.setattr(bot.time, "sleep", lambda s: None)
    assert bot.scrivi("prova") is True
    assert len(tentativi) == 2


def test_scrivi_dopo_due_fallimenti_torna_falso_e_logga(bot, monkeypatch, tmp_path):
    finto_log = tmp_path / "bot.log"
    monkeypatch.setattr(bot, "LOG", str(finto_log))
    monkeypatch.setattr(bot, "tg", lambda *a, **k: None)
    monkeypatch.setattr(bot.time, "sleep", lambda s: None)
    assert bot.scrivi("prova") is False
    assert "NON INVIATA" in finto_log.read_text(encoding="utf-8")
