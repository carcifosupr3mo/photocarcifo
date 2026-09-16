"""Ricerca multi-parola: ogni parola della query e' una condizione AND
indipendente, non una frase esatta da cercare cosi' com'e' scritta.

Fino al 26/08/2026 "raduno manno" cercava letteralmente "%raduno manno%":
un titolo come "Raduno Zona Industriale Manno" non veniva mai trovato,
perche' le due parole non stanno una attaccata all'altra nel titolo vero.
Questi test usano dati reali del database (stesso stile del resto della
suite) invece di inventare album finti: se il caso concreto "raduno manno"
esiste davvero nell'archivio lo verificano su quello, altrimenti verificano
la stessa proprieta' costruendo la query a partire da un titolo vero preso
dal database.
"""
import re

import pytest

from app.database import get_db


def _titoli_in(testo: str) -> list:
    return re.findall(r"<h3>([^<]+)</h3>", testo)


def _album_pubblico_multiparola(conn):
    """Un album pubblico, non nascosto, il cui titolo ha almeno due parole
    di almeno 3 lettere: serve per costruire una query con le parole
    sparse (non consecutive) e verificare che venga comunque trovato."""
    righe = conn.execute(
        "SELECT id, title FROM nodes WHERE is_private=0 AND hidden=0 "
        "AND length(title) > 6").fetchall()
    for r in righe:
        parole = [p for p in r["title"].split() if len(p) >= 3]
        if len(parole) >= 2:
            return r["id"], r["title"], parole
    return None


def test_raduno_manno_trova_raduno_zona_industriale_manno(client):
    """Caso concreto segnalato: le due parole non sono consecutive nel
    titolo reale, la ricerca deve comunque trovarlo."""
    with get_db() as conn:
        riga = conn.execute(
            "SELECT id, title FROM nodes WHERE is_private=0 AND hidden=0 "
            "AND lower(title) LIKE '%raduno%' AND lower(title) LIKE '%manno%'"
            " LIMIT 1").fetchone()
    if not riga:
        pytest.skip("nessun album 'raduno ... manno' nei dati reali")
    r = client.get("/", params={"q": "raduno manno"})
    assert r.status_code == 200
    assert riga["title"] in _titoli_in(r.text), \
        f"'{riga['title']}' non trovato cercando 'raduno manno'"


def test_ordine_delle_parole_non_conta(client):
    """'manno raduno' deve trovare lo stesso risultato di 'raduno manno'."""
    with get_db() as conn:
        riga = conn.execute(
            "SELECT id, title FROM nodes WHERE is_private=0 AND hidden=0 "
            "AND lower(title) LIKE '%raduno%' AND lower(title) LIKE '%manno%'"
            " LIMIT 1").fetchone()
    if not riga:
        pytest.skip("nessun album 'raduno ... manno' nei dati reali")
    a = _titoli_in(client.get("/", params={"q": "raduno manno"}).text)
    b = _titoli_in(client.get("/", params={"q": "manno raduno"}).text)
    assert riga["title"] in a
    assert riga["title"] in b


def test_tre_parole_sparse_nel_titolo(client):
    """'raduno zona manno' (tre parole, non tutte consecutive nel titolo
    reale tipo 'Raduno Zona Industriale Manno') deve trovare comunque
    l'album."""
    with get_db() as conn:
        riga = conn.execute(
            "SELECT id, title FROM nodes WHERE is_private=0 AND hidden=0 "
            "AND lower(title) LIKE '%raduno%' AND lower(title) LIKE '%zona%' "
            "AND lower(title) LIKE '%manno%' LIMIT 1").fetchone()
    if not riga:
        pytest.skip("nessun album 'raduno ... zona ... manno' nei dati reali")
    r = client.get("/", params={"q": "raduno zona manno"})
    assert riga["title"] in _titoli_in(r.text)


def test_due_parole_generiche_di_un_titolo_vero(client):
    """Proprieta' generale (non legata a 'raduno'/'manno'): prese due
    parole qualsiasi di un titolo pubblico vero, cercarle insieme deve
    trovare quel titolo, anche se non sono consecutive nella query."""
    with get_db() as conn:
        trovato = _album_pubblico_multiparola(conn)
    if not trovato:
        pytest.skip("nessun album pubblico con titolo multi-parola nei dati")
    _id, titolo, parole = trovato
    query = f"{parole[0]} {parole[-1]}"
    r = client.get("/", params={"q": query})
    assert titolo in _titoli_in(r.text), \
        f"'{titolo}' non trovato cercando '{query}' (parole: {parole})"


def test_singola_parola_comportamento_invariato(client):
    """Una sola parola continua a funzionare come prima (nessuna AND da
    soddisfare con se stessa, e' semplicemente il caso base)."""
    with get_db() as conn:
        riga = conn.execute(
            "SELECT title FROM nodes WHERE is_private=0 AND hidden=0 "
            "AND length(title) > 4 LIMIT 1").fetchone()
    if not riga:
        pytest.skip("nessun album pubblico nei dati")
    parola = riga["title"].split()[0]
    if len(parola) < 3:
        pytest.skip("prima parola del titolo troppo corta per un test utile")
    r = client.get("/", params={"q": parola})
    assert r.status_code == 200
    assert riga["title"] in _titoli_in(r.text)


def test_match_parziale_prefisso_ancora_attivo(client):
    """'radun' (prefisso di 'raduno') deve continuare a trovare gli album
    con 'raduno' nel titolo, esattamente come prima di questo fix."""
    with get_db() as conn:
        riga = conn.execute(
            "SELECT title FROM nodes WHERE is_private=0 AND hidden=0 "
            "AND lower(title) LIKE '%raduno%' LIMIT 1").fetchone()
    if not riga:
        pytest.skip("nessun album 'raduno' nei dati reali")
    r = client.get("/", params={"q": "radun"})
    assert riga["title"] in _titoli_in(r.text)


def test_parola_mancante_esclude_lalbum(client):
    """Se una delle parole della query non compare da nessuna parte
    nell'album, l'album non deve comparire nei risultati (e' l'AND, non
    l'OR, che deve valere fra le parole)."""
    with get_db() as conn:
        riga = conn.execute(
            "SELECT title FROM nodes WHERE is_private=0 AND hidden=0 "
            "AND lower(title) LIKE '%raduno%' LIMIT 1").fetchone()
    if not riga:
        pytest.skip("nessun album 'raduno' nei dati reali")
    query = "raduno xyzxyznonesisteparola123"
    r = client.get("/", params={"q": query})
    assert riga["title"] not in _titoli_in(r.text)


def test_album_hidden_escluso_dalla_ricerca_multiparola(client, dati):
    """Un album nascosto non deve comparire nemmeno con la nuova ricerca
    multi-parola, qualunque siano le parole cercate."""
    if not dati.get("slug_nascosto"):
        pytest.skip("nessun album nascosto nei dati di prova")
    with get_db() as conn:
        riga = conn.execute(
            "SELECT title FROM nodes WHERE slug=? AND hidden=1",
            (dati["slug_nascosto"],)).fetchone()
    if not riga or len(riga["title"].split()) < 1:
        pytest.skip("titolo dell'album nascosto non utilizzabile per il test")
    parola = riga["title"].split()[0]
    r = client.get("/", params={"q": f"{parola} {parola}"})
    assert riga["title"] not in _titoli_in(r.text)


def test_album_privato_escluso_dalla_ricerca_multiparola(client, dati):
    """Un album privato, per un visitatore anonimo senza il cookie di
    sblocco, non deve comparire nella ricerca multi-parola."""
    if not dati.get("slug_privato"):
        pytest.skip("nessun album privato nei dati di prova")
    with get_db() as conn:
        riga = conn.execute(
            "SELECT title FROM nodes WHERE slug=? AND is_private=1",
            (dati["slug_privato"],)).fetchone()
    if not riga:
        pytest.skip("album privato non trovato")
    parola = riga["title"].split()[0]
    if len(parola) < 3:
        pytest.skip("prima parola del titolo privato troppo corta")
    r = client.get("/", params={"q": f"{parola} {parola}"})
    assert riga["title"] not in _titoli_in(r.text)


def test_ricerca_numero_foto_non_influenzata_dal_fix(client, dati):
    """Il fix riguarda solo _cerca_cartelle: la ricerca per numero foto
    (via app.numeri) deve continuare a funzionare come prima."""
    if not dati.get("media_id"):
        pytest.skip("nessuna foto pubblica nei dati di prova")
    with get_db() as conn:
        numero = conn.execute(
            "SELECT numero FROM media_numeri WHERE media_id=? LIMIT 1",
            (dati["media_id"],)).fetchone()
    if not numero:
        pytest.skip("nessun numero OCR associato a una foto pubblica")
    r = client.get("/", params={"q": str(numero["numero"])})
    assert r.status_code == 200
