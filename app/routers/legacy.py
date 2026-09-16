"""Router degli indirizzi storici: la galleria Piwigo usata prima di questo sito.

Google ha ancora in archivio migliaia di indirizzi della vecchia galleria
(/index.php?/category/... e /picture.php?/...). Finche' rispondono "pagina
non trovata", Search Console li segnala come errori e la reputazione
accumulata in anni da quelle pagine va persa.

Qui vengono riconosciuti e rimandati in modo permanente all'album
corrispondente di oggi: la vecchia categoria "swiss-cup-ginevra-22-03-2025"
diventa /n/swiss-cup-ginevra-22-03-2025. Dove la corrispondenza non esiste
(le vecchie categorie identificate solo da un numero, di cui non resta
traccia) si risponde "410 Gone": dice a Google che la pagina e' sparita per
sempre e va tolta dall'indice, mentre un semplice 404 lo lascerebbe
ritentare per mesi.
"""
import re

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from ..database import get_db
from ..templating import templates

router = APIRouter()

# Nella vecchia galleria l'indirizzo aveva questa forma:
#   /index.php?/category/nome-album
#   /index.php?/category/905/start-999&lang=it_IT
#   /picture.php?/4785/category/gara-swiss-jump-tour-biasca-05-07-2025
# La parte utile e' sempre quella subito dopo "category/".
_CATEGORIA = re.compile(r"category/([^&/?]+)")

# Alcuni album erano registrati con il prefisso "album-": album-2025-2 e'
# diventato semplicemente 2025-2.
_PREFISSI = ("album-",)


def _slug_richiesto(query: str):
    """Nome dell'album chiesto dal vecchio indirizzo, se riconoscibile."""
    trovato = _CATEGORIA.search(query or "")
    if not trovato:
        return None
    nome = trovato.group(1).strip().lower()
    # Le categorie numeriche erano identificate solo dal numero interno di
    # Piwigo: non c'e' modo di risalire all'album, non vanno indovinate.
    return None if not nome or nome.isdigit() else nome


def _album_pubblico(nome: str):
    """Album pubblico corrispondente, provando anche senza il vecchio prefisso."""
    candidati = [nome]
    for prefisso in _PREFISSI:
        if nome.startswith(prefisso):
            candidati.append(nome[len(prefisso):])
    with get_db() as conn:
        for slug in candidati:
            riga = conn.execute(
                "SELECT slug FROM nodes WHERE slug=? AND hidden=0 AND is_private=0",
                (slug,)).fetchone()
            if riga:
                return riga["slug"]
    return None


def _sparita(request: Request):
    """Pagina della vecchia galleria che non esiste piu' e non tornera'."""
    return templates.TemplateResponse(request, "errors/404.html", {"codice": 410},
        status_code=410)


def _instrada(request: Request):
    nome = _slug_richiesto(request.url.query)
    if nome:
        slug = _album_pubblico(nome)
        if slug:
            # 301: permanente. E' quello che sposta su /n/... la reputazione
            # che l'indirizzo vecchio si era guadagnato.
            return RedirectResponse(url=f"/n/{slug}", status_code=301)
        return _sparita(request)
    # Elenco generale della vecchia galleria: oggi il suo posto e' la
    # pagina iniziale, che mostra tutti gli album.
    if "categories" in (request.url.query or "") or not request.url.query:
        return RedirectResponse(url="/", status_code=301)
    return _sparita(request)


@router.get("/index.php", include_in_schema=False)
def vecchia_categoria(request: Request):
    return _instrada(request)


@router.get("/picture.php", include_in_schema=False)
def vecchia_fotografia(request: Request):
    """Le singole foto non hanno piu' una pagina propria: si va all'album.

    Nel vecchio indirizzo l'album e' scritto accanto alla fotografia, quindi
    il visitatore arriva comunque esattamente dove si aspettava.
    """
    return _instrada(request)
