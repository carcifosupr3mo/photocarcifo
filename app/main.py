"""Entrypoint FastAPI Photocarcifo - navigazione ad albero."""
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.routing import Match
from fastapi.staticfiles import StaticFiles

from . import lingue
from .config import get_settings
from .database import init_db, svuota_stat, svuota_node_stat
from .cli import _seed_admin
from .security import security_headers
from .deps import _RedirectToLogin, redirect_to_login
from .templating import templates, COOKIE_STILE
from .routers import (tree, media, auth, admin, seo, admin_nodes, twofa,
                      upload, trash, preferiti, pref_admin, raduni, legacy,
                      lingua, recensioni, contattami, statistiche)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    _seed_admin()
    yield
    svuota_stat()        # non perdere le visite in coda
    svuota_node_stat()   # ne' le statistiche per album


settings = get_settings()

app = FastAPI(title="Photocarcifo", docs_url=None, redoc_url=None,
              openapi_url=None, lifespan=lifespan)

_STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


# Pagine degli album raggiungibili con una sola forma di indirizzo.
# /n/bmx/ e /n/bmx mostrano la stessa cosa: senza questa regola la prima
# rispondeva con uno spostamento "temporaneo", che i motori di ricerca
# trattano come una pagina a se' invece di riconoscerla come duplicato.
# Il pannello di amministrazione e' escluso: li' alcuni indirizzi finiscono
# davvero con la barra.
_CON_BARRA = ("/n/", "/p/")


@app.middleware("http")
async def barra_finale(request: Request, call_next):
    percorso = request.url.path
    if (request.method in ("GET", "HEAD") and percorso.endswith("/")
            and any(percorso.startswith(p) for p in _CON_BARRA)):
        pulito = percorso.rstrip("/")
        if pulito:
            # Il pezzo di lingua e' gia' stato tolto dall'indirizzo a monte:
            # va rimesso, altrimenti chi apre /en/n/bmx/ finisce sulla
            # versione italiana per il solo fatto di aver scritto una barra
            # di troppo.
            pulito = getattr(request.state, "pc_prefisso", "") + pulito
            if request.url.query:
                pulito += "?" + request.url.query
            return RedirectResponse(url=pulito, status_code=301)
    return await call_next(request)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    for key, value in security_headers().items():
        response.headers.setdefault(key, value)

    if "text/html" in response.headers.get("content-type", ""):
        # La pagina esce in due forme a seconda del biscotto del foglio di
        # stile, e cambia anche con la lingua e con l'essere entrati o no
        # nel pannello. Va detto SEMPRE, non solo la prima volta: prima
        # questa riga stava dentro il ramo qui sotto, e la versione
        # leggera — quella che riceve chi torna, cioe' la piu' comune —
        # usciva senza. Una cache che non sa da cosa dipende una pagina la
        # riusa per la richiesta sbagliata.
        vecchio = response.headers.get("vary")
        if "cookie" not in (vecchio or "").lower():
            response.headers["vary"] = f"{vecchio}, Cookie" if vecchio else "Cookie"

        # Le pagine si costruiscono in sette millisecondi e cambiano quando
        # arriva una galleria nuova: non si tengono da parte. Senza questa
        # riga ogni browser decideva per conto suo quanto tenersele, e chi
        # tornava poteva non vedere per giorni le fotografie appena messe.
        response.headers.setdefault("Cache-Control", "private, no-cache")

        # Segno che a questo browser il foglio di stile e' gia' arrivato
        # dentro la pagina: dalla prossima gli si manda il collegamento,
        # che lui ha in cache, invece di rispedirglielo. Vedi templating.py.
        if request.cookies.get(COOKIE_STILE) != "1":
            response.set_cookie(COOKIE_STILE, "1", max_age=30 * 24 * 3600,
                                samesite="lax", secure=True, path="/")
    return response


# ---------------------------------------------------------------------------
# La lingua nell'indirizzo
#
# Prima la lingua stava solo in un cookie: ogni pagina aveva un indirizzo
# solo e i motori di ricerca vedevano soltanto l'italiano. Le traduzioni
# esistevano ma per Google non esistevano, e chi cerca "bmx photos Ticino"
# in inglese non arrivava qui.
#
# Adesso l'inglese sta in /en/..., il francese in /fr/... e cosi' via.
# L'italiano resta senza prefisso, com'era: nessun collegamento gia'
# consegnato cambia e l'archivio dell'indice non va rifatto.
#
# Questo strato fa tre cose, nell'ordine:
#   1. toglie il prefisso dall'indirizzo prima che il sito lo esamini, cosi'
#      nessuna rotta ha dovuto essere riscritta;
#   2. manda chi ha gia' scelto una lingua sull'indirizzo giusto, invece di
#      mostrargli l'italiano;
#   3. rimette il prefisso su tutti i collegamenti della pagina che esce,
#      cosi' navigando non si ricasca in italiano al primo clic.
#
# Il punto 3 si fa qui e non nei modelli di pagina apposta: i collegamenti
# sono centinaia, sparsi in una ventina di file, e basta dimenticarne uno
# perche' il visitatore inglese si ritrovi in italiano senza capire perche'.
# Qui la regola e' scritta una volta sola.
_AUTOMI_LINGUA = ("bot", "spider", "crawl", "slurp", "facebookexternalhit",
                  "preview", "monitor")

# href="/qualcosa" e action="/qualcosa", ma non "//altrosito.ch" e non gli
# indirizzi completi con http davanti: quelli o portano fuori dal sito o
# sono gia' scritti per esteso (canonical, hreflang, dati strutturati) e
# vanno lasciati stare.
_COLLEGAMENTO = re.compile(r'\b(href|action)="/(?!/)([^"]*)"')


def _va_tradotto(percorso: str) -> bool:
    if not lingue.traducibile("/" + percorso):
        return False
    # gia' in un'altra lingua: non si accumulano due prefissi
    primo = percorso.split("/", 1)[0]
    return primo not in lingue.CODICI


def _pagina_esiste(request: Request, percorso: str) -> bool:
    """Esiste davvero una pagina a questo indirizzo?

    Serve per non spostare in un'altra lingua chi ha chiesto qualcosa che
    non c'e'. Prima qualsiasi indirizzo inventato — /ads.txt, /manifest.json,
    le mille porte che provano gli scanner — riceveva prima un 302 verso
    /en/ads.txt e solo dopo il "non esiste": un giro in piu' per tutti, e
    per i motori di ricerca una catena di rimandi che finisce nel nulla,
    moltiplicata per cinque lingue.

    Si chiede all'elenco delle rotte, che e' l'unico che lo sa davvero.
    Costa il confronto di una quarantina di espressioni: microsecondi.
    """
    finto = dict(request.scope)
    finto["path"] = percorso
    for rotta in request.app.routes:
        try:
            esito, _ = rotta.matches(finto)
        except Exception:
            continue
        if esito == Match.FULL:
            return True
    return False


@app.middleware("http")
async def lingua_nell_indirizzo(request: Request, call_next):
    percorso = request.url.path
    codice, pulito = lingue.separa_prefisso(percorso)
    metodo_di_lettura = request.method in ("GET", "HEAD")

    # /it/... non esiste: l'italiano e' senza prefisso. Chi ci arriva viene
    # spostato una volta per sempre, altrimenti la stessa pagina avrebbe due
    # indirizzi e tornerebbero i doppioni.
    if codice == lingue.PREDEFINITA and metodo_di_lettura:
        destinazione = pulito + (f"?{request.url.query}" if request.url.query else "")
        return RedirectResponse(url=destinazione, status_code=301)

    # Il prefisso vale solo dove esiste davvero una traduzione. /en/p/<link>
    # o /en/admin non devono rispondere: sarebbero un secondo indirizzo per
    # la stessa cosa, e sugli album riservati un secondo indirizzo e' anche
    # un secondo modo di ritrovarseli in giro. Non togliendo il prefisso non
    # c'e' nessuna rotta che corrisponda, e la risposta e' "non esiste".
    if codice and not lingue.traducibile(pulito):
        codice = None

    if codice and percorso == f"/{codice}" and metodo_di_lettura:
        # "/en" e "/en/" sono la stessa pagina: se ne tiene una sola, quella
        # con la barra, che e' anche quella dichiarata come ufficiale.
        destinazione = f"/{codice}/" + (f"?{request.url.query}"
                                        if request.url.query else "")
        return RedirectResponse(url=destinazione, status_code=301)

    if codice:
        # L'indirizzo comanda: da qui in poi il sito lavora sul percorso
        # senza prefisso, e sa in che lingua deve rispondere.
        request.scope["path"] = pulito
        request.scope["raw_path"] = pulito.encode()
        request.state.pc_lingua = codice
        request.state.pc_prefisso = f"/{codice}"
    else:
        request.state.pc_prefisso = ""
        # Chi ha gia' scelto una lingua non deve rileggersi la home in
        # italiano ogni volta. I programmi automatici non vengono spostati:
        # devono vedere l'italiano all'indirizzo italiano, sempre.
        if (metodo_di_lettura and lingue.traducibile(percorso)
                and _pagina_esiste(request, percorso)
                and "text/html" in request.headers.get("accept", "")):
            agente = (request.headers.get("user-agent") or "").lower()
            if not any(s in agente for s in _AUTOMI_LINGUA):
                preferita = lingue.lingua_di(request)
                if preferita != lingue.PREDEFINITA:
                    meta = lingue.con_prefisso(percorso, preferita)
                    if request.url.query:
                        meta += f"?{request.url.query}"
                    # Spostamento provvisorio: dipende da chi guarda, non
                    # dalla pagina. Un permanente direbbe a Google che
                    # l'indirizzo italiano non esiste piu'.
                    return RedirectResponse(url=meta, status_code=302)

    risposta = await call_next(request)

    if not codice or "text/html" not in risposta.headers.get("content-type", ""):
        return risposta

    # Da qui in poi la risposta arriva a pezzi, come un rubinetto: per
    # riscrivere i collegamenti bisogna raccoglierla tutta prima. Sono
    # pagine di qualche centinaio di kilobyte, non file da scaricare, e i
    # file veri (immagini, ZIP) non passano di qua perche' non sono HTML.
    pezzi = [pezzo async for pezzo in risposta.body_iterator]
    corpo = b"".join(pezzi)

    testo = _COLLEGAMENTO.sub(
        lambda m: (f'{m.group(1)}="/{codice}/{m.group(2)}"'
                   if _va_tradotto(m.group(2))
                   else f'{m.group(1)}="/{m.group(2)}"'),
        corpo.decode("utf-8", "replace"))
    nuovo = testo.encode("utf-8")

    intestazioni = dict(risposta.headers)
    intestazioni.pop("content-length", None)   # la lunghezza e' cambiata
    return Response(content=nuovo, status_code=risposta.status_code,
                    headers=intestazioni, media_type=risposta.media_type)


@app.exception_handler(_RedirectToLogin)
async def _login_redirect_handler(request: Request, exc: _RedirectToLogin):
    return redirect_to_login()


@app.exception_handler(404)
async def not_found(request: Request, exc):
    accept = request.headers.get("accept", "")
    if "text/html" not in accept:
        return PlainTextResponse("Not Found", status_code=404)
    return templates.TemplateResponse(request, "errors/404.html", {}, status_code=404)


@app.exception_handler(500)
async def server_error(request: Request, exc):
    return templates.TemplateResponse(request, "errors/500.html", {}, status_code=500)


# ---------------------------------------------------------------------------
# Gli altri errori: una pagina, non un blocco di dati
#
# Fino a qui il sito aveva una pagina per il 404 e una per il 500. Tutto il
# resto usciva come lo produce la libreria, cioe' cosi':
#
#   {"detail":[{"type":"int_parsing","loc":["path","media_id"], ...}]}
#
# Bastava un indirizzo copiato male o un collegamento vecchio troncato per
# vederselo in faccia. A chi guarda non dice nulla, e a chi cerca punti
# deboli dice il nome dei parametri e che tipo si aspettano.
#
# Le chiamate che il sito fa a se' stesso col JavaScript continuano a
# ricevere i dati: sono loro a saperli leggere, e la pagina in cui girano
# mostra gia' il proprio messaggio.
_TITOLI_ERRORE = {400: "err.400", 403: "err.403", 429: "err.429"}


def _vuole_una_pagina(request: Request) -> bool:
    """Vero se dall'altra parte c'e' un browser che sta aprendo una pagina."""
    return "text/html" in request.headers.get("accept", "")


def _pagina_errore(request: Request, codice: int, dettaglio: str = ""):
    from .lingue import traduci, lingua_di
    lingua = lingua_di(request)
    chiave = _TITOLI_ERRORE.get(codice, "err.gen")
    # Il dettaglio scritto da noi (per esempio "Spazio quasi esaurito") e'
    # comprensibile e si mostra; quello generato dalla libreria no.
    testo = dettaglio if (dettaglio and " " in dettaglio) else traduci(f"{chiave}_txt", lingua)
    return templates.TemplateResponse(request, "errors/errore.html", {"codice": codice,
         "titolo": traduci(f"{chiave}_tit", lingua), "testo": testo},
        status_code=codice)


@app.exception_handler(StarletteHTTPException)
async def errore_http(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        return await not_found(request, exc)
    if _vuole_una_pagina(request) and 400 <= exc.status_code < 500:
        return _pagina_errore(request, exc.status_code, str(exc.detail or ""))
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code,
                        headers=getattr(exc, "headers", None))


@app.exception_handler(RequestValidationError)
async def dati_non_validi(request: Request, exc: RequestValidationError):
    if _vuole_una_pagina(request):
        return _pagina_errore(request, 400)
    # Alle chiamate del JavaScript si risponde come prima, ma senza
    # rimandare indietro il valore ricevuto: potrebbe contenere qualsiasi
    # cosa e non serve a chi legge.
    campi = [".".join(str(p) for p in e.get("loc", [])) for e in exc.errors()]
    return JSONResponse({"detail": "Dati non validi", "campi": campi},
                        status_code=422)


app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(media.router)
app.include_router(seo.router)
app.include_router(admin_nodes.router)
app.include_router(twofa.router)
app.include_router(upload.router)
app.include_router(trash.router)
app.include_router(preferiti.router)
app.include_router(pref_admin.router)
app.include_router(statistiche.router)
app.include_router(raduni.router)
app.include_router(recensioni.router)
app.include_router(contattami.router)
app.include_router(lingua.router)
app.include_router(legacy.router)  # indirizzi della vecchia galleria
app.include_router(tree.router)   # tree per ultimo: contiene la root "/"


# Ogni pagina leggibile deve rispondere anche alla richiesta HEAD, cioe'
# "dimmi solo le intestazioni, non mandarmi il contenuto".
#
# WhatsApp, Telegram e Facebook la usano come primo passo quando qualcuno
# incolla un collegamento: chiedono le intestazioni per sapere che tipo di
# pagina e' e quanto pesa, e solo dopo la scaricano davvero. FastAPI
# registrava le rotte per il solo GET, quindi quella prima richiesta
# riceveva "metodo non consentito" e l'anteprima non veniva nemmeno
# tentata: il collegamento usciva nudo, senza immagine ne' titolo.
for _rotta in app.routes:
    _metodi = getattr(_rotta, "methods", None)
    if _metodi and "GET" in _metodi:
        _metodi.add("HEAD")


@app.get("/healthz", response_class=PlainTextResponse)
def healthz():
    return "ok"
