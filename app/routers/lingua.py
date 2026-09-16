"""Cambio della lingua del sito.

Fa due cose insieme. Porta alla stessa pagina nella lingua scelta, che ha
un indirizzo suo (/en/n/bmx, /fr/n/bmx...), e ricorda la scelta in un
cookie, cosi' chi torna sul sito senza prefisso viene portato subito nella
sua lingua invece di rileggersi l'italiano.

Dopo il cambio si resta esattamente sulla pagina da cui si e' partiti: chi
stava guardando un album ci ritrova, invece di ritrovarsi in home.
"""
from fastapi import APIRouter, Request, status
from fastapi.responses import RedirectResponse

from .. import lingue

router = APIRouter()

# Un anno: la lingua e' una preferenza stabile, non va richiesta a ogni visita.
DURATA = 365 * 24 * 3600


def _ritorno(request: Request, da: str) -> str:
    """Pagina a cui tornare dopo il cambio.

    Si accettano solo indirizzi interni al sito. Senza questo controllo il
    parametro potrebbe essere usato per spedire un visitatore su un sito
    esterno partendo da un collegamento che sembra nostro.
    """
    candidato = da or request.headers.get("referer", "") or "/"
    if candidato.startswith("http"):
        base = str(request.base_url).rstrip("/")
        if not candidato.startswith(base + "/") and candidato != base:
            return "/"
        candidato = candidato[len(base):] or "/"
    if not candidato.startswith("/") or candidato.startswith("//"):
        return "/"
    return candidato


@router.get("/lingua/{codice}")
def cambia(request: Request, codice: str, da: str = ""):
    scelta = lingue.normalizza(codice)
    # La pagina di partenza puo' gia' avere un prefisso, se si passa da una
    # lingua all'altra: si toglie quello vecchio prima di mettere il nuovo,
    # altrimenti si finirebbe su /fr/en/n/bmx.
    dove = _ritorno(request, da)
    percorso, _, coda = dove.partition("?")
    _, nudo = lingue.separa_prefisso(percorso)
    meta = lingue.con_prefisso(nudo, scelta) if lingue.traducibile(nudo) else nudo
    if coda:
        meta += "?" + coda
    risposta = RedirectResponse(url=meta, status_code=status.HTTP_303_SEE_OTHER)
    # I programmi automatici seguono questi collegamenti 1.462 volte al
    # giorno, nonostante robots.txt lo vieti e nonostante rel="nofollow".
    # Non fanno danno, ma e' lavoro sprecato: questa intestazione lo dice
    # una terza volta, nel punto in cui non si puo' non leggerla.
    risposta.headers["X-Robots-Tag"] = "noindex, nofollow"
    risposta.set_cookie(lingue.COOKIE, scelta, max_age=DURATA,
                        samesite="lax", secure=True, path="/")
    return risposta
