"""Il download multiplo dentro il browser interno delle app su iPhone.

La parte che decide cosa fare vive nel browser (app/static/js/app.js): questi
controlli tengono ferme le due cose da cui quella decisione dipende e che
starebbero in silenzio se qualcuno le togliesse — gli attacchi nella pagina
che lo script cerca, e le scritte tradotte che il riquadro mostra.

Il percorso vero e proprio, a browser aperto, e' in tests/browser/
test_ios_webview.js (Playwright su WebKit, il motore di iOS).
"""
import re

from app.lingue import CODICI, TESTI

# Le chiavi del riquadro: il nome le raccoglie tutte, cosi' aggiungerne una
# senza tradurla fa fallire questo controllo invece di far comparire la
# chiave grezza sullo schermo di chi scarica.
CHIAVI_RIQUADRO = sorted(c for c in TESTI if c.startswith("js.ios_"))


def test_riquadro_ios_ha_le_sue_scritte():
    """Le scritte esistono e coprono i tre momenti del riquadro."""
    assert CHIAVI_RIQUADRO, "nessuna scritta per il riquadro iOS"
    attese = {
        "js.ios_titolo_preparo", "js.ios_preparo", "js.ios_avanzamento",
        "js.ios_titolo_pronto", "js.ios_pronto", "js.ios_salva",
        "js.ios_salvato", "js.ios_titolo", "js.ios_titolo_app",
        "js.ios_testo", "js.ios_troppe", "js.ios_troppo_grande",
        "js.ios_apri_safari", "js.ios_copia", "js.ios_copiato",
        "js.ios_annulla",
    }
    mancanti = attese - set(CHIAVI_RIQUADRO)
    assert not mancanti, f"scritte mancanti: {sorted(mancanti)}"


def test_riquadro_ios_tradotto_ovunque():
    """Nessuna lingua resta indietro: chi scarica legge nella sua."""
    for chiave in CHIAVI_RIQUADRO:
        for lingua in CODICI:
            testo = TESTI[chiave].get(lingua)
            assert testo, f"{chiave} non tradotta in {lingua}"


def test_segnaposto_coerenti_tra_le_lingue():
    """{app}, {n}, {max}, {mb}: se una traduzione ne perde uno, la frase
    esce monca (o peggio mostra il segnaposto grezzo)."""
    for chiave in CHIAVI_RIQUADRO:
        versioni = TESTI[chiave]
        atteso = set(re.findall(r"\{(\w+)\}", versioni["it"]))
        for lingua in CODICI:
            trovati = set(re.findall(r"\{(\w+)\}", versioni[lingua]))
            assert trovati == atteso, (
                f"{chiave} in {lingua}: segnaposto {sorted(trovati)} "
                f"invece di {sorted(atteso)}")


def test_scarica_tutto_dichiara_quante_foto(client):
    """Il numero di fotografie sta nella pagina: dentro una webview di iOS
    e' quello che decide se tenerle in memoria o mandare in Safari."""
    import pytest

    from app.database import get_db
    # Serve un album da cui si possa davvero scaricare, e che le fotografie
    # le contenga di persona: in una cartella che ne raccoglie altre la
    # barra dei bottoni non compare, e il controllo non avrebbe senso.
    with get_db() as conn:
        album = conn.execute(
            "SELECT n.slug FROM nodes n WHERE n.is_private=0 AND n.hidden=0 "
            "AND n.downloads_enabled=1 "
            "AND EXISTS (SELECT 1 FROM media m WHERE m.node_id=n.id) "
            "LIMIT 1").fetchone()
    if not album:
        pytest.skip("nessun album pubblico con download attivo")
    r = client.get(f"/n/{album['slug']}", headers={"accept": "text/html"})
    assert r.status_code == 200
    bottone = re.search(r'<a[^>]*id="dlTutto"[^>]*>', r.text)
    assert bottone, "manca il bottone 'scarica tutto'"
    assert 'data-quante="' in bottone.group(0), (
        "il bottone non dice quante fotografie sono: il percorso iOS non "
        "puo' piu' decidere")


def test_condivisione_multipla_passa_dallo_stesso_percorso(client, dati):
    """Su /fs/{token} 'scarica tutte' era un semplice link, e dentro la
    webview di iOS non si sarebbe salvato mai: deve avere l'aggancio dello
    script come la pagina di un album."""
    import pytest

    from app.database import get_db
    if not dati["media_id"]:
        pytest.skip("nessuna fotografia pubblica nel database di prova")
    token = "prova-ios-webview"
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO condivisioni(token, media_ids, created_at) "
            "VALUES(?,?,datetime('now'))",
            (token, f"{dati['media_id']},{dati['media_id']}"))
    try:
        r = client.get(f"/fs/{token}", headers={"accept": "text/html"})
        assert r.status_code == 200
        bottone = re.search(r'<a[^>]*id="dlTutto"[^>]*>', r.text)
        assert bottone, "la condivisione multipla non aggancia lo script"
        assert 'data-quante="' in bottone.group(0)
    finally:
        with get_db() as conn:
            conn.execute("DELETE FROM condivisioni WHERE token=?", (token,))
