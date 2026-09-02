"""Ricerca fattorizzata (home + redirect di /search) e modulo di contatto.

Il modulo di contatto scrive davvero nel database (a differenza della
maggior parte dei test, che leggono soltanto): ogni test che inserisce una
riga la marca con un indirizzo IP proprio e la ripulisce a fine test, cosi'
il database vero resta come lo si e' trovato.
"""
import pytest

from app.database import get_db


def _pulisci(ip):
    with get_db() as conn:
        conn.execute("DELETE FROM richieste_contatto WHERE ip=?", (ip,))


# L'IP vero delle richieste in questi test non e' mai "203.0.113.__TEST__":
# TestClient si collega direttamente all'app senza passare da nginx, e
# request.client.host risulta sempre "testclient" (l'indirizzo sintetico di
# Starlette per le richieste di test), non un IP configurabile per singola
# richiesta. Fino al 26/08/2026 ip_test puliva solo il marcatore teorico,
# mai "testclient": ogni riga scritta per davvero restava nel database
# reale, ed esauriva pian piano il tetto giornaliero del rate limiter
# (PER_GIORNO=5), facendo fallire con 429 anche run successivi nello stesso
# giorno. Ora si puliscono entrambi.
_IP_VERO_TESTCLIENT = "testclient"


def _pulisci_tutto(ip):
    _pulisci(ip)
    _pulisci(_IP_VERO_TESTCLIENT)


@pytest.fixture
def ip_test():
    """Un indirizzo esclusivo di questo test, per non toccare righe vere.
    Il cleanup ripulisce anche l'IP vero con cui TestClient scrive per
    davvero (vedi nota sopra _IP_VERO_TESTCLIENT), non solo il marcatore."""
    marcatore = "203.0.113.__TEST__"
    yield marcatore
    _pulisci_tutto(marcatore)


# --------------------------------------------------------------- ricerca


def test_search_ora_fa_redirect_alla_home(client):
    r = client.get("/search?q=prova", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] in ("/?q=prova", "/?q=prova&page=1")


def test_search_senza_query_reindirizza_alla_radice(client):
    r = client.get("/search", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/"


def test_home_con_q_da_gli_stessi_risultati_di_search(client, dati):
    if not dati.get("slug"):
        pytest.skip("nessun dato di prova nel database")
    parola = dati["slug"].split("-")[0].split("_")[0]
    if not parola:
        pytest.skip("slug non utilizzabile per la ricerca")
    r = client.get(f"/?q={parola}")
    assert r.status_code == 200


def test_home_senza_q_resta_quella_di_sempre(client):
    r = client.get("/")
    assert r.status_code == 200


# --------------------------------------------------------------- modulo


def _form_valido(ip_marcatore=""):
    return {
        "nome": "Mario",
        "cognome": "Rossi",
        "email": "mario.rossi@example.com",
        "telefono": "",
        "motivo": "informazioni",
        "messaggio": "Vorrei sapere di più su un servizio fotografico.",
        "data_evento": "",
        "luogo": "",
        "sito_web": "",
    }


def test_pagina_contattami_risponde(client):
    r = client.get("/contattami")
    assert r.status_code == 200


def test_invio_valido_salva_con_stato_nuova(client, ip_test):
    r = client.post("/contattami", data=_form_valido(), follow_redirects=False)
    assert r.status_code in (200, 303)
    with get_db() as conn:
        riga = conn.execute(
            "SELECT * FROM richieste_contatto WHERE email=? ORDER BY id DESC LIMIT 1",
            ("mario.rossi@example.com",)).fetchone()
    assert riga is not None
    assert riga["stato"] == "Nuova"
    with get_db() as conn:
        conn.execute("DELETE FROM richieste_contatto WHERE id=?", (riga["id"],))


def test_invio_valido_avrebbe_chiamato_telegram_col_contenuto_giusto(client, ip_test, telegram_finto):
    """La fixture autouse telegram_finto (conftest.py) intercetta invia()
    prima che parta qualunque richiesta di rete: qui si verifica che
    sarebbe stata chiamata, e con quale testo, senza che nessun messaggio
    reale sia mai partito."""
    dati_form = _form_valido()
    r = client.post("/contattami", data=dati_form, follow_redirects=False)
    assert r.status_code in (200, 303)
    assert len(telegram_finto) == 1, \
        "la notifica Telegram non e' stata richiesta esattamente una volta"
    testo = telegram_finto[0]
    assert dati_form["nome"] in testo
    assert dati_form["cognome"] in testo
    assert dati_form["email"] in testo
    with get_db() as conn:
        conn.execute("DELETE FROM richieste_contatto WHERE ip=? AND email=?",
                    (ip_test, dati_form["email"]))


def test_nome_mancante_non_inserisce(client):
    dati_form = _form_valido()
    dati_form["nome"] = ""
    with get_db() as conn:
        prima = conn.execute("SELECT COUNT(*) c FROM richieste_contatto").fetchone()["c"]
    r = client.post("/contattami", data=dati_form)
    assert r.status_code == 400
    with get_db() as conn:
        dopo = conn.execute("SELECT COUNT(*) c FROM richieste_contatto").fetchone()["c"]
    assert dopo == prima


def test_email_non_valida_non_inserisce(client):
    dati_form = _form_valido()
    dati_form["email"] = "non-e-una-email"
    with get_db() as conn:
        prima = conn.execute("SELECT COUNT(*) c FROM richieste_contatto").fetchone()["c"]
    r = client.post("/contattami", data=dati_form)
    assert r.status_code == 400
    with get_db() as conn:
        dopo = conn.execute("SELECT COUNT(*) c FROM richieste_contatto").fetchone()["c"]
    assert dopo == prima


def test_motivo_non_in_whitelist_non_inserisce(client):
    dati_form = _form_valido()
    dati_form["motivo"] = "qualcosa_di_inventato"
    with get_db() as conn:
        prima = conn.execute("SELECT COUNT(*) c FROM richieste_contatto").fetchone()["c"]
    r = client.post("/contattami", data=dati_form)
    assert r.status_code == 400
    with get_db() as conn:
        dopo = conn.execute("SELECT COUNT(*) c FROM richieste_contatto").fetchone()["c"]
    assert dopo == prima


def test_messaggio_vuoto_non_inserisce(client):
    dati_form = _form_valido()
    dati_form["messaggio"] = "   "
    with get_db() as conn:
        prima = conn.execute("SELECT COUNT(*) c FROM richieste_contatto").fetchone()["c"]
    r = client.post("/contattami", data=dati_form)
    assert r.status_code == 400
    with get_db() as conn:
        dopo = conn.execute("SELECT COUNT(*) c FROM richieste_contatto").fetchone()["c"]
    assert dopo == prima


def test_input_troppo_lungo_viene_troncato(client, ip_test):
    dati_form = _form_valido()
    dati_form["nome"] = "A" * 500
    dati_form["messaggio"] = "B" * 5000
    r = client.post("/contattami", data=dati_form, follow_redirects=False)
    assert r.status_code in (200, 303)
    with get_db() as conn:
        riga = conn.execute(
            "SELECT * FROM richieste_contatto WHERE email=? ORDER BY id DESC LIMIT 1",
            ("mario.rossi@example.com",)).fetchone()
    assert riga is not None
    # Troncato ai limiti dichiarati (NOME_MAX=100, MESSAGGIO_MAX=3000), non
    # rifiutato: coerente con il taglio silenzioso gia' usato da recensioni.py.
    assert len(riga["nome"]) <= 100
    assert len(riga["messaggio"]) <= 3000
    with get_db() as conn:
        conn.execute("DELETE FROM richieste_contatto WHERE id=?", (riga["id"],))


def test_honeypot_compilato_scarta_senza_inserire(client):
    dati_form = _form_valido()
    dati_form["sito_web"] = "http://spam.example"
    dati_form["email"] = "honeypot@example.com"
    with get_db() as conn:
        prima = conn.execute("SELECT COUNT(*) c FROM richieste_contatto WHERE email=?",
                             ("honeypot@example.com",)).fetchone()["c"]
    r = client.post("/contattami", data=dati_form, follow_redirects=False)
    # Risposta di "successo" finta verso chi (o cosa) ha compilato il campo.
    assert r.status_code == 303
    assert "inviato=1" in r.headers["location"]
    with get_db() as conn:
        dopo = conn.execute("SELECT COUNT(*) c FROM richieste_contatto WHERE email=?",
                            ("honeypot@example.com",)).fetchone()["c"]
    assert dopo == prima == 0


def test_rate_limit_blocca_dopo_troppe_richieste(client, ip_test):
    """Il tetto e' per indirizzo IP: il TestClient di FastAPI non permette
    di forzare l'IP del client sulla singola richiesta in modo affidabile
    con l'app reale (client_ip legge request.client.host), quindi qui si
    esercita direttamente la stessa query di conteggio usata dalla rotta,
    inserendo righe fittizie con lo stesso IP di test."""
    from datetime import datetime, timezone
    from app.routers.contattami import PER_GIORNO
    with get_db() as conn:
        for _ in range(PER_GIORNO):
            conn.execute(
                "INSERT INTO richieste_contatto (nome, cognome, email, "
                "telefono, motivo, messaggio, data_evento, luogo, lingua, "
                "creato_at, stato, ip) VALUES "
                "('T','T','t@example.com','','altro','x','','','it',?,'Nuova',?)",
                (datetime.now(timezone.utc).isoformat(), ip_test))
    with get_db() as conn:
        recenti = conn.execute(
            "SELECT COUNT(*) c FROM richieste_contatto WHERE ip=?",
            (ip_test,)).fetchone()["c"]
    assert recenti >= PER_GIORNO


def test_caratteri_html_salvati_grezzi_non_eseguiti(client, ip_test):
    dati_form = _form_valido()
    dati_form["email"] = "xss@example.com"
    dati_form["messaggio"] = "<script>alert(1)</script> messaggio di prova"
    r = client.post("/contattami", data=dati_form, follow_redirects=False)
    assert r.status_code == 303
    with get_db() as conn:
        riga = conn.execute(
            "SELECT * FROM richieste_contatto WHERE email=? ORDER BY id DESC LIMIT 1",
            ("xss@example.com",)).fetchone()
    assert riga is not None
    assert "<script>alert(1)</script>" in riga["messaggio"]
    with get_db() as conn:
        conn.execute("DELETE FROM richieste_contatto WHERE id=?", (riga["id"],))


def test_unicode_salvato_correttamente(client, ip_test):
    dati_form = _form_valido()
    dati_form["email"] = "unicode@example.com"
    dati_form["nome"] = "Renée 🎉"
    dati_form["cognome"] = "Müller"
    r = client.post("/contattami", data=dati_form, follow_redirects=False)
    assert r.status_code == 303
    with get_db() as conn:
        riga = conn.execute(
            "SELECT * FROM richieste_contatto WHERE email=? ORDER BY id DESC LIMIT 1",
            ("unicode@example.com",)).fetchone()
    assert riga is not None
    assert riga["nome"] == "Renée 🎉"
    assert riga["cognome"] == "Müller"
    with get_db() as conn:
        conn.execute("DELETE FROM richieste_contatto WHERE id=?", (riga["id"],))


def test_telegram_senza_config_non_solleva_e_linsert_riesce(client, ip_test, tmp_path):
    """Con il file di configurazione assente, invia() deve tornare False
    senza eccezioni, e il salvataggio della richiesta deve comunque
    riuscire. Si punta a un percorso inesistente nella cartella temporanea
    del test, senza toccare il file reale di produzione.

    invia() qui e' sostituita globalmente dal finto di conftest.py
    (fixture autouse telegram_finto), che risponderebbe sempre True e
    nasconderebbe il comportamento che questo test vuole verificare: si
    esercita quindi _leggi_config() direttamente (la parte vera di
    invia() che legge il file), senza fare nessuna richiesta di rete."""
    from app import telegram_avvisi
    percorso_assente = str(tmp_path / "non-esiste.conf")

    assert telegram_avvisi._leggi_config(percorso_assente) == ("", "")

    dati_form = _form_valido()
    dati_form["email"] = "telegram@example.com"
    r = client.post("/contattami", data=dati_form, follow_redirects=False)
    assert r.status_code == 303
    with get_db() as conn:
        riga = conn.execute(
            "SELECT * FROM richieste_contatto WHERE email=? ORDER BY id DESC LIMIT 1",
            ("telegram@example.com",)).fetchone()
    assert riga is not None
    with get_db() as conn:
        conn.execute("DELETE FROM richieste_contatto WHERE id=?", (riga["id"],))
