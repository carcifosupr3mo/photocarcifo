"""Filtri, ricerca e ordinamento su GET /admin/richieste.

Inserisce righe fittizie con un prefisso riconoscibile e le cancella
sempre a fine test, come gia' fa test_contattami.py per non sporcare il
database vero."""
from datetime import datetime, timedelta, timezone

import pytest

from app.database import get_db

_PREFISSO = "ZzTestFiltri"


def _inserisci(nome, cognome, email, motivo, stato, giorni_fa=0):
    creato = (datetime.now(timezone.utc) - timedelta(days=giorni_fa)).isoformat()
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO richieste_contatto "
            "(nome, cognome, email, telefono, motivo, messaggio, data_evento, "
            " luogo, lingua, creato_at, stato, ip) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (nome, cognome, email, "", motivo, "messaggio di prova", "", "",
             "it", creato, stato, "127.0.0.1"))
        return cur.lastrowid


@pytest.fixture
def righe_prova():
    id_nuova = _inserisci(_PREFISSO + "Anna", "Bianchi",
                          "annabianchi.ztest@example.com", "matrimonio", "Nuova", giorni_fa=0)
    id_chiusa = _inserisci(_PREFISSO + "Marco", "Verdi",
                           "marcoverdi.ztest@example.com", "ritratti", "Chiusa", giorni_fa=10)
    yield {"nuova": id_nuova, "chiusa": id_chiusa}
    with get_db() as conn:
        conn.execute("DELETE FROM richieste_contatto WHERE id IN (?,?)",
                     (id_nuova, id_chiusa))


def test_anonimo_reindirizzato_al_login(client):
    r = client.get("/admin/richieste", follow_redirects=False)
    assert r.status_code in (302, 303)
    assert "login" in r.headers.get("location", "")


def test_filtro_stato_mostra_solo_quello_stato(client_admin, righe_prova):
    r = client_admin.get("/admin/richieste", params={"stato": "Nuova"})
    assert r.status_code == 200
    assert (_PREFISSO + "Anna") in r.text
    assert (_PREFISSO + "Marco") not in r.text


def test_ricerca_per_nome_trova_la_riga_giusta(client_admin, righe_prova):
    r = client_admin.get("/admin/richieste", params={"q": _PREFISSO + "Anna"})
    assert r.status_code == 200
    assert (_PREFISSO + "Anna") in r.text
    assert (_PREFISSO + "Marco") not in r.text


def test_ricerca_per_email_trova_la_riga_giusta(client_admin, righe_prova):
    r = client_admin.get("/admin/richieste", params={"q": "marcoverdi.ztest@example.com"})
    assert r.status_code == 200
    assert (_PREFISSO + "Marco") in r.text
    assert (_PREFISSO + "Anna") not in r.text


def test_ricerca_per_motivo_trova_la_riga_giusta(client_admin, righe_prova):
    r = client_admin.get("/admin/richieste", params={"q": "matrimonio"})
    assert r.status_code == 200
    assert (_PREFISSO + "Anna") in r.text


def test_ricerca_query_inesistente_nessun_risultato(client_admin, righe_prova):
    r = client_admin.get("/admin/richieste", params={"q": "stringaCheNonEsisteDavveroXyz123"})
    assert r.status_code == 200
    assert (_PREFISSO + "Anna") not in r.text
    assert (_PREFISSO + "Marco") not in r.text


def test_ordinamento_recenti_e_vecchi(client_admin, righe_prova):
    r_recenti = client_admin.get("/admin/richieste",
                                 params={"q": _PREFISSO, "ordine": "recenti"})
    r_vecchi = client_admin.get("/admin/richieste",
                                params={"q": _PREFISSO, "ordine": "vecchi"})
    assert r_recenti.status_code == 200 and r_vecchi.status_code == 200
    pos_anna_recenti = r_recenti.text.find(_PREFISSO + "Anna")
    pos_marco_recenti = r_recenti.text.find(_PREFISSO + "Marco")
    assert pos_anna_recenti != -1 and pos_marco_recenti != -1
    assert pos_anna_recenti < pos_marco_recenti  # la piu' recente (Anna) prima

    pos_anna_vecchi = r_vecchi.text.find(_PREFISSO + "Anna")
    pos_marco_vecchi = r_vecchi.text.find(_PREFISSO + "Marco")
    assert pos_marco_vecchi < pos_anna_vecchi  # la piu' vecchia (Marco) prima


def test_stato_non_valido_ignorato_senza_errore(client_admin, righe_prova):
    r = client_admin.get("/admin/richieste", params={"stato": "InventatoDiSana"})
    assert r.status_code == 200  # nessun 500: il filtro non valido cade nel "tutte"
