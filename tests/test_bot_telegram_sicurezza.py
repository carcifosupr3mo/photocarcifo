"""Audit di sicurezza del bot Telegram: puo' un estraneo, conoscendo
username e comandi, ottenere qualcosa dal bot?

Il controllo di autorizzazione (funzione autorizzato() in
script/photocarcifo-bot.py) e' unico e centralizzato: chat.type=="private"
+ chat.id esattamente uguale a quello configurato. Non esiste nel codice
alcuna callback_query/InlineKeyboard (nessun pulsante inline e' mai stato
implementato), quindi non c'e' una seconda superficie da testare li' — lo
si conferma esplicitamente con un test che legge il sorgente.

Nessuna chiamata reale a api.telegram.org: stessa fixture `bot` di
test_bot_telegram.py (tg() sempre sostituita, LOG sempre puntato a un file
temporaneo).
"""
import time

import pytest

from test_bot_telegram import _carica_modulo, _messaggi_inviati  # noqa: F401 (riuso fixture-adiacenti)


CHAT_AUTORIZZATA_ESEMPIO = "111111111"  # id di test, non quello reale


@pytest.fixture
def bot(monkeypatch, tmp_path):
    """Stessa fixture di test_bot_telegram.py, duplicata qui invece di
    importata: pytest non condivide fixture fra file diversi senza un
    conftest.py dedicato, e aggiungerne uno solo per questo altererebbe
    conftest.py principale del progetto, fuori scope di un audit che deve
    toccare solo il bot."""
    modulo = _carica_modulo()
    chiamate = []

    def tg_finta(metodo, attesa=20, **dati):
        chiamate.append({"metodo": metodo, "dati": dati})
        if metodo == "sendMessage":
            return {"ok": True, "result": {"message_id": len(chiamate)}}
        return {"ok": True, "result": []}

    monkeypatch.setattr(modulo, "tg", tg_finta)
    monkeypatch.setattr(modulo, "LOG", str(tmp_path / "bot.log"))
    monkeypatch.setattr(modulo, "esegui", lambda *a, **k: "(finto nei test)")
    modulo._CHIAMATE = chiamate
    modulo._attesa.clear()
    modulo._in_corso = None
    modulo._ULTIMO_RESPINTO.clear()
    yield modulo


def _msg_privato(chat_id, testo, tipo="private"):
    """Un update Telegram minimo e realistico: solo i campi che il bot
    legge davvero (chat.id, chat.type, text)."""
    return {"chat": {"id": chat_id, "type": tipo},
            "from": {"id": chat_id, "is_bot": False, "username": "chiunque"},
            "text": testo}


# --------------------------------------------------------- rete reale: NO

def test_nessuna_chiamata_di_rete_reale_in_questo_file(bot, monkeypatch):
    import urllib.request

    def esplodi(*a, **k):
        raise AssertionError("chiamata di rete reale intercettata")

    monkeypatch.setattr(urllib.request, "urlopen", esplodi)
    bot.autorizzato(_msg_privato(bot.CHAT, "/applica"))
    bot.autorizzato(_msg_privato("999999999", "/applica"))
    bot.gestisci("/stato")  # gestisci() non fa mai I/O di rete da sola


# ------------------------------------------------------- funzione centrale

def test_autorizzato_accetta_solo_chat_privata_corretta(bot):
    assert bot.autorizzato(_msg_privato(bot.CHAT, "/stato")) is True


def test_autorizzato_rifiuta_chat_id_diverso(bot):
    assert bot.autorizzato(_msg_privato("999999999", "/stato")) is False


def test_autorizzato_rifiuta_id_corretto_ma_tipo_gruppo(bot):
    """Il caso che conta di piu': anche se per assurdo un id di gruppo
    coincidesse con quello configurato (impossibilita' pratica in
    Telegram — gli id di gruppo sono negativi, quelli di chat privata
    positivi — ma il controllo esplicito su type toglie ogni dubbio),
    l'autorizzazione deve comunque fallire."""
    assert bot.autorizzato(_msg_privato(bot.CHAT, "/applica", tipo="group")) is False
    assert bot.autorizzato(_msg_privato(bot.CHAT, "/applica", tipo="supergroup")) is False
    assert bot.autorizzato(_msg_privato(bot.CHAT, "/applica", tipo="channel")) is False


def test_autorizzato_rifiuta_msg_senza_chat(bot):
    assert bot.autorizzato({}) is False
    assert bot.autorizzato({"chat": {}}) is False


def test_autorizzazione_non_guarda_lo_username(bot):
    """Prova diretta del punto 23: uno username identico o simile a
    qualsiasi valore plausibile non deve avere alcun peso — autorizzato()
    non legge affatto msg["from"]["username"], solo chat.id/chat.type."""
    finto_ma_username_sospetto = _msg_privato(
        "999999999", "/applica")
    finto_ma_username_sospetto["from"]["username"] = "photocarcifo_admin"
    assert bot.autorizzato(finto_ma_username_sospetto) is False
    # Anche con lo stesso username del vero admin (se mai lo si sapesse),
    # cambiare SOLO l'username non basta a passare.
    finto_ma_username_sospetto["from"]["username"] = "qualunque_nome_anche_giusto"
    assert bot.autorizzato(finto_ma_username_sospetto) is False


# ------------------------------------------------------ giro principale

def _un_giro(bot, msg):
    """Replica la porzione rilevante del loop in main(): legge
    autorizzato(), e se vero chiama gestisci()+scrivi(), altrimenti non
    fa nulla (nessuna scrivi()). Usata per testare l'INTERO percorso, non
    solo autorizzato() isolata."""
    if not bot.autorizzato(msg):
        chat = msg.get("chat", {}) or {}
        if bot._log_respinto_va_scritto(chat.get("id", "?")):
            bot.loga(f"RESPINTO tipo={chat.get('type', '?')} chat_id={chat.get('id', '?')}")
        return None
    testo = msg.get("text", "")
    risposta = bot.gestisci(testo)
    bot.scrivi(risposta)
    return risposta


@pytest.mark.parametrize("comando", [
    "start", "help", "aiuto", "stato", "errori", "visite", "spazio",
    "foto", "recensioni", "numeri", "diagnosi", "controlla", "bloccati",
    "sblocca", "salva", "riavvia", "applica", "health",
])
def test_estraneo_prova_ogni_comando_nessuno_funziona(bot, comando):
    """Il test fondamentale richiesto: un estraneo che conosce PERFETTAMENTE
    la sintassi di ogni comando (compresa la conferma "SI" per i quattro
    pericolosi) non deve ottenere nulla — nessuna risposta, nessuna
    chiamata a esegui(), nessuna lettura del database."""
    msg = _msg_privato("999999999", f"/{comando}")
    r = _un_giro(bot, msg)
    assert r is None
    assert _messaggi_inviati(bot) == []
    assert bot._CHIAMATE == []  # nessuna chiamata a tg() di alcun tipo


@pytest.mark.parametrize("comando", ["salva", "riavvia", "applica", "sblocca"])
def test_estraneo_con_conferma_si_non_esegue_azione_pericolosa(bot, comando, monkeypatch):
    """Anche conoscendo che serve "SI" per confermare, e anche costruendo
    un finto stato di conferma gia' presente (come se l'estraneo avesse
    indovinato o intercettato il flusso) — l'autorizzazione viene PRIMA
    di qualunque logica di conferma, quindi non importa cosa c'e' in
    _attesa: l'estraneo non arriva mai a gestisci()."""
    eseguiti = []
    monkeypatch.setattr(bot, "esegui", lambda *a, **k: eseguiti.append(1))
    bot._attesa[comando] = time.time()  # anche con conferma gia' "valida"
    msg = _msg_privato("999999999", f"/{comando} SI")
    r = _un_giro(bot, msg)
    assert r is None
    assert not eseguiti
    assert _messaggi_inviati(bot) == []


def test_comando_famoso_applica_respinto_anche_se_perfettamente_scritto(bot, monkeypatch):
    """La prova esplicitamente richiesta: /applica, scritto esattamente
    come nella documentazione, con conferma "SI" gia' valida, da un
    estraneo che ha indovinato tutto — deve fallire comunque, prima di
    ogni altra cosa."""
    eseguiti = []
    monkeypatch.setattr(bot, "esegui", lambda *a, **k: eseguiti.append(1))
    bot._attesa["applica"] = time.time()
    assert _un_giro(bot, _msg_privato("42", "/applica SI")) is None
    assert not eseguiti


def test_gruppo_con_id_autorizzato_non_esegue_nulla(bot, monkeypatch):
    """Il comando admin dentro un gruppo (anche se qualcuno riuscisse ad
    avere l'id di chat coincidente, ipotesi teorica) non deve fare
    nulla: risultato atteso, nessuna azione."""
    eseguiti = []
    monkeypatch.setattr(bot, "esegui", lambda *a, **k: eseguiti.append(1))
    bot._attesa["applica"] = time.time()
    msg = _msg_privato(bot.CHAT, "/applica SI", tipo="supergroup")
    assert _un_giro(bot, msg) is None
    assert not eseguiti


def test_utente_autorizzato_in_chat_privata_funziona_normalmente(bot, monkeypatch):
    """Controllo di non-regressione: il vero admin, nella vera chat
    privata, deve continuare a poter usare il bot normalmente."""
    r = _un_giro(bot, _msg_privato(bot.CHAT, "/stato"))
    assert r is not None
    assert _messaggi_inviati(bot) == [r]


# --------------------------------------------------------- callback query

def test_nessuna_callback_query_nel_codice(bot):
    """Non esiste alcun pulsante inline/callback_query in questo bot: lo
    si conferma leggendo il sorgente, non solo assumendolo. Se in futuro
    qualcuno aggiungesse un InlineKeyboardButton, questo test fallirebbe
    e ricorderebbe di applicargli lo stesso controllo autorizzato()."""
    from pathlib import Path
    sorgente = (Path(__file__).resolve().parent.parent / "script" /
               "photocarcifo-bot.py").read_text(encoding="utf-8")
    for termine in ("callback_query", "InlineKeyboard", "answerCallbackQuery"):
        assert termine not in sorgente, (
            f"trovato {termine!r}: questo file di test presume che non esistano "
            "callback inline, va esteso se ne viene aggiunta una")


# ------------------------------------------------------------------- log

def test_tentativo_respinto_viene_loggato_senza_testo_del_messaggio(bot, tmp_path, monkeypatch):
    finto_log = tmp_path / "bot.log"
    monkeypatch.setattr(bot, "LOG", str(finto_log))
    msg = _msg_privato("999999999", "/applica SI qualcosa di privato scritto qui")
    _un_giro(bot, msg)
    contenuto = finto_log.read_text(encoding="utf-8")
    assert "RESPINTO" in contenuto
    assert "999999999" in contenuto
    assert "qualcosa di privato" not in contenuto
    assert bot.TOKEN not in contenuto


def test_log_respinto_ha_un_rate_limit(bot, tmp_path, monkeypatch):
    """Molti tentativi ravvicinati dalla stessa chat non autorizzata non
    devono riempire il log riga per riga: solo il primo entro la finestra
    va scritto."""
    finto_log = tmp_path / "bot.log"
    monkeypatch.setattr(bot, "LOG", str(finto_log))
    for _ in range(20):
        _un_giro(bot, _msg_privato("999999999", "/applica"))
    contenuto = finto_log.read_text(encoding="utf-8") if finto_log.exists() else ""
    assert contenuto.count("RESPINTO") == 1


def test_log_respinto_chat_diverse_non_si_bloccano_a_vicenda(bot, tmp_path, monkeypatch):
    finto_log = tmp_path / "bot.log"
    monkeypatch.setattr(bot, "LOG", str(finto_log))
    _un_giro(bot, _msg_privato("111", "/applica"))
    _un_giro(bot, _msg_privato("222", "/applica"))
    contenuto = finto_log.read_text(encoding="utf-8")
    assert contenuto.count("RESPINTO") == 2


# --------------------------------------------------------------- token

def test_token_non_hardcoded_nel_sorgente(bot):
    """Il token non deve mai comparire come stringa letterale nel
    sorgente: deve arrivare SOLO da leggi_config(), mai da nessun'altra
    parte del file."""
    from pathlib import Path
    sorgente = (Path(__file__).resolve().parent.parent / "script" /
               "photocarcifo-bot.py").read_text(encoding="utf-8")
    if bot.TOKEN:
        assert bot.TOKEN not in sorgente


def test_token_non_finisce_in_nessuna_risposta_telegram(bot):
    """Nessun messaggio inviato all'utente autorizzato deve mai contenere
    il token (es. per debug lasciato per errore)."""
    _un_giro(bot, _msg_privato(bot.CHAT, "/stato"))
    for testo in _messaggi_inviati(bot):
        assert bot.TOKEN not in testo


def test_config_ha_permessi_ristretti_in_produzione():
    """Il file di configurazione reale (non quello dei test) deve essere
    leggibile solo dal proprietario. Verificato sul filesystem reale
    perche' e' l'unico modo di controllare i permessi effettivi — se il
    file non esiste in questo ambiente (es. CI senza il server reale), il
    test si salta invece di fallire per un motivo estraneo alla sicurezza
    del codice."""
    import os
    import stat as stat_mod
    percorso = "/etc/photocarcifo-telegram.conf"
    if not os.path.exists(percorso):
        pytest.skip("file di configurazione non presente in questo ambiente")
    modo = os.stat(percorso).st_mode
    leggibile_da_altri = bool(modo & (stat_mod.S_IRGRP | stat_mod.S_IROTH))
    assert not leggibile_da_altri, (
        "il file di configurazione Telegram e' leggibile da altri utenti/gruppi")
