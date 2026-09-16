"""Regressione: la suite non deve mai scrivere sul database di produzione.

Trovato da un audit di sicurezza (08/09/2026): client.post("/condividi/
selezione") - una scrittura vera, non un test in un ambiente a parte -
lasciava una condivisione reale e funzionante nel database vero. Vedi
conftest.py per il meccanismo di isolamento (copia sanificata + guardia
su sqlite3.connect) che questo file dimostra concretamente.
"""
import pytest

import conftest as _conftest
from app.database import get_db


def test_il_database_di_test_non_e_quello_di_produzione():
    """Prova diretta che get_db() punta altrove: il percorso usato
    dall'applicazione durante i test non e' mai data/photocarcifo.db."""
    from app.config import get_settings
    percorso_in_uso = get_settings().db_path.resolve()
    assert percorso_in_uso != _conftest.DB_PRODUZIONE
    assert percorso_in_uso == _conftest.DB_TEST.resolve()


def test_connettersi_al_db_di_produzione_fallisce_subito():
    """La guardia fail-closed: un tentativo diretto di sqlite3.connect()
    sul file vero deve fallire immediatamente, non silenziosamente
    riuscire. Non e' un test che si fida della fixture - e' la barriera
    stessa, verificata."""
    import sqlite3
    with pytest.raises(RuntimeError, match="BLOCCATO"):
        sqlite3.connect(str(_conftest.DB_PRODUZIONE))


def test_condividi_scrive_solo_sul_db_isolato_di_test(client, dati):
    """Riproduce esattamente l'operazione che, prima del fix, lasciava
    una condivisione vera in produzione: la crea, verifica che sia finita
    nel database di TEST, e controlla che il file di produzione non
    abbia cambiato un solo byte nel frattempo."""
    if not dati["media_id"]:
        pytest.skip("nessuna fotografia pubblica nel database di test")

    with get_db() as conn:
        prima = conn.execute(
            "SELECT COUNT(*) c FROM condivisioni").fetchone()["c"]

    r = client.post("/condividi/selezione",
                    data={"ids": str(dati["media_id"])})
    assert r.status_code == 200

    with get_db() as conn:
        dopo = conn.execute(
            "SELECT COUNT(*) c FROM condivisioni").fetchone()["c"]
    assert dopo == prima + 1, \
        "la condivisione non risulta nel database di test"

    # get_db() qui sopra e' quello dell'applicazione (punta al database di
    # test, vedi il primo test di questo file). La prova che il file VERO
    # non si e' mosso usa una lettura di byte pura, non sqlite3: e'
    # esattamente il canale con cui conftest.py aveva preso l'impronta
    # iniziale, prima di installare qualunque guardia.
    impronta_ora = _conftest.impronta_file(_conftest.DB_PRODUZIONE)
    assert impronta_ora == _conftest.IMPRONTA_PRODUZIONE_INIZIALE, \
        "il database di produzione e' cambiato durante la suite"
