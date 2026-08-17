"""Ogni pagina pubblica risponde, in tutte e cinque le lingue.

Questi test hanno una ragione precisa. Il 17/08/2026 un modello di pagina e'
stato modificato per usare una funzione che il processo in esecuzione non
conosceva ancora: per pochi secondi ogni pagina del sito ha risposto
"errore interno", e in quella finestra e' passato Googlebot. Un test che
apre tutte le pagine avrebbe fermato la cosa prima che arrivasse in rete.
"""
import pytest

LINGUE = ["", "en/", "fr/", "de/", "es/"]
PAGINE = ["", "novita", "chi-sono", "recensioni", "privacy", "search"]


@pytest.mark.parametrize("lingua", LINGUE)
@pytest.mark.parametrize("pagina", PAGINE)
def test_pagine_fisse(client, lingua, pagina):
    r = client.get(f"/{lingua}{pagina}", headers={"accept": "text/html"})
    assert r.status_code == 200, f"/{lingua}{pagina} ha risposto {r.status_code}"
    assert "<html" in r.text.lower()


@pytest.mark.parametrize("lingua", LINGUE)
def test_album_pubblico(client, dati, lingua):
    if not dati["slug"]:
        pytest.skip("nessun album pubblico nel database")
    r = client.get(f"/{lingua}n/{dati['slug']}", headers={"accept": "text/html"})
    assert r.status_code == 200


def test_lingua_segue_indirizzo(client):
    """L'indirizzo comanda sulla lingua: e' cio' che rende indicizzabili
    le traduzioni. Se tornasse a comandare il cookie, ogni indirizzo
    mostrerebbe cinque contenuti diversi e Google ne terrebbe uno solo."""
    atteso = {"": "it", "en/": "en", "fr/": "fr", "de/": "de", "es/": "es"}
    for prefisso, codice in atteso.items():
        r = client.get(f"/{prefisso}", headers={"accept": "text/html"})
        assert f'<html lang="{codice}"' in r.text, f"/{prefisso} non e' in {codice}"


def test_italiano_senza_prefisso(client):
    """/it/... non deve esistere: sarebbe un secondo indirizzo per la
    stessa pagina, cioe' un doppione per i motori di ricerca."""
    r = client.get("/it/", follow_redirects=False)
    assert r.status_code == 301
    assert r.headers["location"] == "/"


def test_hreflang_reciproci(client, dati):
    """Ogni pagina dichiara tutte e cinque le versioni piu' x-default.
    Se una mancasse, Google scarterebbe quella traduzione."""
    r = client.get(f"/n/{dati['slug']}", headers={"accept": "text/html"})
    for codice in ("it", "en", "fr", "de", "es", "x-default"):
        assert f'hreflang="{codice}"' in r.text, f"manca hreflang {codice}"


def test_una_sola_pagina_ufficiale(client, dati):
    """Il canonical di ogni lingua punta a se stesso, non all'italiano."""
    r = client.get(f"/fr/n/{dati['slug']}", headers={"accept": "text/html"})
    assert f'rel="canonical" href="https://photocarcifo.ch/fr/n/{dati["slug"]}"' in r.text


def test_collegamenti_restano_nella_lingua(client):
    """Navigando dentro una lingua non si deve ricadere in italiano."""
    r = client.get("/es/", headers={"accept": "text/html"})
    interni = [x for x in r.text.split('href="')[1:]]
    album = [x.split('"')[0] for x in interni if x.startswith("/n/")]
    assert not album, f"collegamenti rimasti in italiano: {album[:3]}"


def test_barra_finale_mantiene_la_lingua(client):
    r = client.get("/fr/n/bmx/", follow_redirects=False)
    assert r.status_code == 301
    assert r.headers["location"] == "/fr/n/bmx"


def test_indirizzi_di_servizio(client):
    for percorso, tipo in (("/robots.txt", "text/plain"),
                           ("/sitemap.xml", "application/xml"),
                           ("/novita.xml", "application/rss+xml"),
                           ("/healthz", "text/plain")):
        r = client.get(percorso)
        assert r.status_code == 200, percorso
        assert tipo in r.headers["content-type"], percorso


def test_sitemap_non_contiene_pagine_riservate(client, dati):
    """Un album privato o nascosto nella sitemap sarebbe un invito a
    indicizzarlo: e' il contrario di cio' per cui e' riservato."""
    mappa = client.get("/sitemap.xml").text
    for chiave in ("slug_privato", "slug_nascosto"):
        if dati[chiave]:
            assert f"/n/{dati[chiave]}<" not in mappa, f"{chiave} finito nella sitemap"
