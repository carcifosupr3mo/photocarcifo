"""Che restare collegati dal telefono non apra porte a nessun altro.

Dal 19/08/2026 il modulo d'accesso ha la spunta «Resta collegato su questo
dispositivo»: la sessione dura novanta giorni invece di uno, e il codice a
sei cifre non viene piu' chiesto su quel dispositivo. E' una comodita' che
tocca la sicurezza, quindi i test qui sotto verificano soprattutto cosa
NON deve succedere.
"""
import time

import pytest


def test_sessione_normale_dura_un_giorno():
    """La spunta e' opzionale: chi non la mette non deve ritrovarsi
    collegato per tre mesi senza averlo chiesto."""
    from app.config import get_settings
    from app.security import create_session, _serializer
    t = create_session(1)
    assert "lungo" not in _serializer().loads(t)
    assert get_settings().session_max_age <= 86400


def test_sessione_lunga_e_dichiarata_dentro_il_biglietto():
    """La durata la decide chi ha fatto l'accesso, e viaggia firmata: non
    e' qualcosa che si possa aggiungere a mano dal browser."""
    from app.security import create_session, read_session, _serializer
    t = create_session(1, lungo=True)
    assert _serializer().loads(t)["lungo"] is True
    assert read_session(t)["uid"] == 1


def test_biglietto_manomesso_non_vale():
    """Cambiando anche un carattere la firma non torna piu'."""
    from app.security import create_session, read_session
    t = create_session(1, lungo=True)
    rovinato = t[:-3] + ("aaa" if not t.endswith("aaa") else "bbb")
    assert read_session(rovinato) is None


def test_sessione_scaduta_non_vale():
    """Novanta giorni sono tanti, ma non infiniti: la firma porta l'orario
    e oltre la durata dichiarata non viene piu' accettata."""
    from itsdangerous import SignatureExpired
    from app.security import create_session, read_session, _serializer
    t = create_session(1, lungo=True)
    time.sleep(1.1)
    with pytest.raises(SignatureExpired):
        _serializer().loads(t, max_age=0)
    assert read_session(t) is not None      # con il metro giusto vale ancora


def test_il_pulsante_sgancia_tutti_i_dispositivi():
    """E' l'unica via d'uscita se un telefono si perde. Deve funzionare
    anche sulle sessioni gia' emesse, non solo sulle prossime."""
    from app.database import get_db
    from app.security import create_session, read_session, dimentica_dispositivi
    with get_db() as conn:
        prima = conn.execute("SELECT fidati_dal FROM users WHERE id=1").fetchone()
        prima = float(prima["fidati_dal"]) if prima else 0.0
    vecchia = create_session(1, lungo=True)
    assert read_session(vecchia) is not None
    try:
        time.sleep(1.1)          # la firma ha il secondo come unita'
        dimentica_dispositivi(1)
        assert read_session(vecchia) is None, \
            "una sessione emessa prima dello sgancio vale ancora"
        nuova = create_session(1, lungo=True)
        assert read_session(nuova) is not None, \
            "dopo lo sgancio non si riesce piu' a entrare"
    finally:
        with get_db() as conn:
            conn.execute("UPDATE users SET fidati_dal=? WHERE id=1", (prima,))


def test_il_dispositivo_ricordato_da_solo_non_apre_niente(client):
    """Il cookie del dispositivo dice "il codice l'hai gia' dato", non
    "sei dentro". Senza password non deve valere nulla."""
    from app.routers.auth import FIDATO_COOKIE, _fidato_serializer
    r = client.get("/admin", cookies={FIDATO_COOKIE: _fidato_serializer().dumps({"uid": 1})},
                   follow_redirects=False)
    assert r.status_code in (302, 303, 307), \
        "il solo cookie del dispositivo ha aperto il pannello"


def test_la_casella_e_spenta_di_suo(client):
    """Su un computer prestato la spunta non deve essere gia' messa."""
    pagina = client.get("/admin/login").text
    assert 'name="ricorda"' in pagina, "la casella non c'e'"
    riga = [r for r in pagina.splitlines() if 'name="ricorda"' in r][0]
    assert "checked" not in riga, "la casella e' spuntata di suo"


def test_nessun_album_privato_resta_senza_link():
    """Un album privato senza link non lo puo' aprire nessuno, nemmeno chi
    lo possiede: dal pannello si finiva su /p/None, che e' un 404."""
    from app.database import get_db
    with get_db() as conn:
        orfani = conn.execute(
            "SELECT id, title FROM nodes WHERE is_private=1 "
            "AND (access_token IS NULL OR access_token='')").fetchall()
    assert not orfani, \
        f"album privati senza link: {[o['title'] for o in orfani]}"


def test_i_modelli_non_scrivono_none_negli_indirizzi():
    """Il modello che stampa un valore assente scrive la parola "None"
    dentro l'indirizzo, e il collegamento porta a una pagina che non
    esiste. Ogni /p/<qualcosa> va protetto da un controllo."""
    import re
    from pathlib import Path
    radice = Path(__file__).resolve().parent.parent / "app" / "templates"
    colpevoli = []
    for f in radice.rglob("*.html"):
        for n, riga in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            for m in re.finditer(r'/p/\{\{\s*([\w.]*token[\w.]*)\s*\}\}', riga):
                nome = m.group(1)
                # va bene se sulla stessa riga c'e' un controllo su quel valore
                if re.search(r"\bif\b[^%]*" + re.escape(nome), riga):
                    continue
                # e va bene nell'azione di un modulo: li' il valore arriva
                # dall'indirizzo che si sta gia' guardando, quindi esiste
                if "action=" in riga:
                    continue
                colpevoli.append(f"{f.name}:{n}")
    assert not colpevoli, f"indirizzi che possono diventare /p/None: {colpevoli}"
