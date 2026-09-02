"""Ogni modello di pagina usa solo cose che esistono davvero.

Il 17/08/2026 un modello e' stato modificato per chiamare una funzione che
il processo in esecuzione non conosceva ancora. I modelli si leggono dal
disco a ogni richiesta, il codice no: per i secondi fra la modifica del
modello e il riavvio, tutte le pagine hanno risposto "errore interno". In
quella finestra e' passato Googlebot.

Questo test legge i modelli e controlla che ogni funzione e ogni filtro
che nominano esista nell'ambiente Jinja dell'applicazione. Non disegna le
pagine (servirebbero i dati di ognuna): guarda i nomi, che e' esattamente
la classe di errore che ci e' costata quelle pagine.
"""
import re
from pathlib import Path

import pytest

MODELLI = sorted((Path(__file__).resolve().parent.parent / "app" / "templates").rglob("*.html"))

# Nomi che Jinja conosce da se' o che arrivano come variabili di pagina:
# non sono funzioni globali e non vanno cercate fra quelle.
INCORPORATI = {
    "range", "dict", "lipsum", "cycler", "joiner", "namespace", "super",
    "self", "loop", "request", "url_for", "format", "int", "str", "len",
}

# Parole di Jinja, non funzioni: "{% if x %}...{% endif %}" scritto in linea
# fa comparire "if(" e "else(" a una lettura ingenua.
PAROLE_JINJA = {
    "if", "else", "elif", "for", "in", "and", "or", "not", "is", "endif",
    "endfor", "set", "block", "extends", "include", "with", "macro", "call",
    "filter", "do", "trans", "endtrans", "raw", "endraw",
}


def _funzioni_chiamate(testo: str) -> set:
    """Nomi chiamati come funzione dentro le graffe di Jinja."""
    nomi = set()
    for blocco in re.findall(r"\{\{(.*?)\}\}|\{%(.*?)%\}", testo, re.S):
        contenuto = blocco[0] or blocco[1]
        for nome in re.findall(r"\b([a-z_][a-z0-9_]*)\s*\(", contenuto):
            nomi.add(nome)
    return nomi


@pytest.mark.parametrize("modello", MODELLI, ids=lambda p: p.name)
def test_il_modello_usa_solo_funzioni_esistenti(app, modello):
    from app.templating import templates
    ambiente = templates.env
    testo = modello.read_text(encoding="utf-8")
    sconosciute = []
    for nome in _funzioni_chiamate(testo):
        if (nome in INCORPORATI or nome in PAROLE_JINJA
                or nome in ambiente.globals or nome in ambiente.filters
                or nome in ambiente.tests):
            continue
        # I metodi chiamati su una variabile (r.get(...), q.strftime(...))
        # hanno un punto davanti: non sono nomi globali.
        if re.search(rf"[.\w]\.{nome}\s*\(", testo):
            continue
        # Le macro definite dentro il modello stesso.
        if re.search(rf"\{{%-?\s*macro\s+{nome}\s*\(", testo):
            continue
        sconosciute.append(nome)
    assert not sconosciute, (
        f"{modello.name} usa nomi che l'applicazione non conosce: {sconosciute}. "
        "Succede quando si modifica un modello prima del codice che gli serve: "
        "il modello si rilegge subito, il codice solo al riavvio.")


@pytest.mark.parametrize("modello", MODELLI, ids=lambda p: p.name)
def test_il_modello_e_sintatticamente_valido(app, modello):
    from app.templating import templates
    from jinja2 import TemplateSyntaxError
    radice = Path(__file__).resolve().parent.parent / "app" / "templates"
    percorso = str(modello.relative_to(radice))
    try:
        templates.env.get_template(percorso)
    except TemplateSyntaxError as errore:
        pytest.fail(f"{percorso}, riga {errore.lineno}: {errore.message}")


def test_le_chiavi_di_traduzione_esistono_in_tutte_le_lingue():
    """Una chiave tradotta in italiano ma non in tedesco non rompe niente:
    ricade sull'italiano. Ma il tedesco si ritrova una frase italiana in
    mezzo, e nessuno se ne accorge finche' non lo segnala un visitatore."""
    from app.lingue import TESTI, CODICI
    buchi = []
    for chiave, versioni in TESTI.items():
        mancanti = [c for c in CODICI if c not in versioni or not versioni[c]]
        if mancanti:
            buchi.append(f"{chiave}: manca {','.join(mancanti)}")
    assert not buchi, "\n".join(buchi)


def test_ogni_chiave_usata_nei_modelli_esiste():
    """t('qualcosa') scritto male non da' errore: mostra la chiave grezza
    al visitatore. Meglio accorgersene qui."""
    from app.lingue import TESTI
    usate = set()
    for modello in MODELLI:
        testo = modello.read_text(encoding="utf-8")
        # \bt( e non t(: senza il confine, "select('equalto'" contiene
        # "t('" e verrebbe letto come una chiave di traduzione.
        usate.update(re.findall(r"\bt\(\s*['\"]([a-z0-9_.]+)['\"]", testo))
    mancanti = sorted(c for c in usate if c not in TESTI)
    assert not mancanti, f"chiavi usate ma mai definite: {mancanti}"
