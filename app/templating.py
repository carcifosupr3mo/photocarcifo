from datetime import datetime
from pathlib import Path
from fastapi.templating import Jinja2Templates
from .config import get_settings

_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

def _human_size(num):
    try: value = float(num)
    except (TypeError, ValueError): return "0 B"
    for unit in ("B","KB","MB","GB","TB"):
        if value < 1024.0:
            return f"{value:.0f} {unit}" if unit=="B" else f"{value:.1f} {unit}"
        value/=1024.0
    return f"{value:.1f} PB"

def _fmt_date(value):
    if not value: return ""
    try:
        dt=datetime.fromisoformat(value.replace("Z","+00:00"))
        return dt.strftime("%d/%m/%Y")
    except Exception: return value

templates.env.filters["human_size"]=_human_size
templates.env.filters["fmt_date"]=_fmt_date
templates.env.globals["site_name"]=lambda:get_settings().site_name
templates.env.globals["site_url"]=lambda:get_settings().site_url
templates.env.globals["now_year"]=lambda:datetime.now().year


# --- Lingua della pagina ---------------------------------------------------
# t("chiave") restituisce il testo nella lingua scelta dal visitatore. La
# lingua si ricava dalla richiesta in corso, che Jinja tiene gia' nel
# contesto: cosi' nei modelli basta scrivere t(...) senza passarla ogni volta.
from jinja2 import pass_context  # noqa: E402
from . import lingue as _lingue  # noqa: E402


def _lingua_corrente(contesto):
    richiesta = contesto.get("request")
    return _lingue.lingua_di(richiesta) if richiesta else _lingue.PREDEFINITA


@pass_context
def _t(contesto, chiave: str) -> str:
    return _lingue.traduci(chiave, _lingua_corrente(contesto))


@pass_context
def _lingua(contesto) -> str:
    return _lingua_corrente(contesto)


@pass_context
def _prefisso(contesto) -> str:
    """Il pezzo di lingua davanti all'indirizzo: "" in italiano, "/en"...

    Serve agli indirizzi scritti per esteso (canonical, hreflang, dati
    strutturati, og:url): quelli non passano dalla riscrittura automatica
    dei collegamenti, che tocca solo quelli che cominciano con una barra.
    """
    richiesta = contesto.get("request")
    return getattr(getattr(richiesta, "state", None), "pc_prefisso", "") or ""


@pass_context
def _alternative(contesto):
    """Elenco (codice, indirizzo completo) della pagina in ogni lingua.

    E' quello che serve per i tag hreflang: dicono a Google che queste
    cinque pagine non sono doppioni ma la stessa cosa in lingue diverse, e
    che a un francese va mostrata quella francese.
    """
    richiesta = contesto.get("request")
    if not richiesta:
        return []
    percorso = richiesta.url.path                  # gia' senza prefisso
    if not _lingue.traducibile(percorso):
        return []
    base = str(get_settings().site_url).rstrip("/")
    return [(c, base + _lingue.con_prefisso(percorso, c)) for c in _lingue.CODICI]


templates.env.globals["t"] = _t
templates.env.globals["lingua"] = _lingua
templates.env.globals["lingue"] = lambda: _lingue.LINGUE
templates.env.globals["pref"] = _prefisso
templates.env.globals["alternative"] = _alternative


# Le condizioni d'uso sono un testo lungo e continuo: tenerle spezzate in
# decine di frasi separate le renderebbe illeggibili da mantenere. Vivono
# quindi come documento intero, uno per lingua.
@pass_context
def _testo_legale(contesto) -> str:
    from .lingue_legale import DOCUMENTO
    scelta = _lingua_corrente(contesto)
    return DOCUMENTO.get(scelta) or DOCUMENTO[_lingue.PREDEFINITA]


templates.env.globals["testo_legale"] = _testo_legale


# Le scritte che il browser costruisce da solo (selezione, visualizzatore,
# avviso iniziale) non passano dai modelli: gli vengono consegnate qui, gia'
# tradotte, come blocco di dati. E' un blocco di dati e non di codice, quindi
# non aggira le regole di sicurezza sugli script della pagina.
@pass_context
def _testi_js(contesto) -> str:
    import json
    voci = _lingue.per_javascript(_lingua_corrente(contesto))
    # "<" viene messo in forma neutra: cosi' nessuna scritta puo' chiudere
    # per sbaglio il blocco in cui si trova.
    return json.dumps(voci, ensure_ascii=False).replace("<", "\\u003c")


templates.env.globals["testi_js"] = _testi_js


def _asset(percorso: str) -> str:
    """Aggiunge la data di modifica del file all'indirizzo.

    Serve a far scaricare subito ai browser la versione nuova di CSS e
    JavaScript, anche quando sono in cache da giorni.
    """
    from pathlib import Path
    base = Path(__file__).parent
    reale = base / percorso.lstrip("/").replace("static/", "static/", 1)
    try:
        return f"{percorso}?v={int(reale.stat().st_mtime)}"
    except OSError:
        return percorso


templates.env.globals["asset"] = _asset


# --- Foglio di stile: incorporato la prima volta, collegato dalla seconda ---
#
# Le due strade hanno ciascuna un difetto opposto.
#
# Incorporandolo, la pagina si disegna al primo viaggio: il browser non deve
# scaricare la pagina, scoprire il foglio e richiederlo. In cambio quei 67 KB
# viaggiano di nuovo a ogni pagina aperta, perche' una cosa scritta dentro la
# pagina non si puo' tenere da parte.
#
# Collegandolo, il foglio si scarica una volta e vale per tutte le pagine
# successive, ma la prima costa un viaggio in piu' prima di vedere qualcosa.
#
# Misurato sul registro degli accessi: 2,2 pagine a visitatore, ma il 59%
# ne apre una sola. Nessuna delle due strade va bene per tutti, quindi si
# usano tutte e due: alla prima pagina il foglio viaggia dentro (nessuna
# attesa in piu' proprio a chi vedra' solo quella) e si lascia un segno nel
# browser; dalla seconda in poi si manda il collegamento, che il browser ha
# gia' in cache per trenta giorni.
#
# I programmi dei motori di ricerca non tengono segni e ricevono sempre la
# versione incorporata: per loro e' la piu' semplice da disegnare.
COOKIE_STILE = "pc_css"


@pass_context
def _stile_da_incorporare(contesto) -> bool:
    """Vero se a questo visitatore il foglio va scritto dentro la pagina."""
    richiesta = contesto.get("request")
    try:
        return richiesta.cookies.get(COOKIE_STILE) != "1"
    except AttributeError:
        return True


templates.env.globals["stile_da_incorporare"] = _stile_da_incorporare

_cache_stile = {"mtime": 0, "testo": ""}


def _stile_incorporato() -> str:
    from pathlib import Path
    percorso = Path(__file__).parent / "static" / "css" / "style.css"
    try:
        mtime = percorso.stat().st_mtime
    except OSError:
        return ""
    if mtime != _cache_stile["mtime"]:
        try:
            testo = percorso.read_text(encoding="utf-8")
        except OSError:
            return ""
        # tolgo commenti e spazi superflui: meno peso, stesso risultato
        import re
        testo = re.sub(r"/\*.*?\*/", "", testo, flags=re.DOTALL)
        testo = re.sub(r"\s*\n\s*", "", testo)
        testo = re.sub(r"\s{2,}", " ", testo)
        testo = re.sub(r"\s*([{}:;,>])\s*", r"\1", testo)
        testo = testo.replace(";}", "}")
        _cache_stile["mtime"] = mtime
        _cache_stile["testo"] = testo
        _scrivi_versione_ridotta(percorso, testo)
    return _cache_stile["testo"]


def _scrivi_versione_ridotta(sorgente, testo: str) -> None:
    """Salva accanto al foglio la sua versione ridotta, per il collegamento.

    Il foglio scritto a mano ha commenti e spazi che servono a chi lo
    mantiene: sono 82 KB, 18 compressi. Ridotto scende a 67, 12 compressi.
    Chi riceve il collegamento invece del testo incorporato deve avere la
    versione ridotta, altrimenti la seconda pagina risparmierebbe meno di
    quanto potrebbe.

    Si riscrive solo quando il foglio cambia. Se la cartella non fosse
    scrivibile non succede niente di grave: resta il file di partenza, che
    e' identico nel risultato e solo un po' piu' pesante.
    """
    try:
        ridotto = sorgente.with_name("style.min.css")
        if ridotto.exists() and ridotto.stat().st_mtime >= sorgente.stat().st_mtime:
            return
        provvisorio = ridotto.with_suffix(".tmp")
        provvisorio.write_text(testo, encoding="utf-8")
        provvisorio.replace(ridotto)
    except OSError:
        pass


def _parte_pubblica() -> str:
    """Il foglio senza le regole che servono solo al pannello.

    Un quarto abbondante del foglio disegna schede degli album, albero
    delle cartelle, caricamento e cestino: cose che un visitatore non
    vedra' mai, e che gli venivano spedite lo stesso dentro ogni prima
    pagina. Il pannello continua a ricevere il foglio intero, cosi' una
    classificazione sbagliata puo' solo togliere una regola al sito
    pubblico — e quel caso lo prende il test, che apre ogni pagina e
    controlla che tutte le classi che usa esistano ancora.
    """
    from .stile_diviso import dividi
    intero = _stile_incorporato()
    if _cache_stile.get("pubblico_da") == intero[:64] and _cache_stile.get("pubblico"):
        return _cache_stile["pubblico"]
    pubblico, _ = dividi(intero)
    _cache_stile["pubblico"] = pubblico
    _cache_stile["pubblico_da"] = intero[:64]
    _scrivi_file_accanto("style-pubblico.min.css", pubblico)
    return pubblico


def _scrivi_file_accanto(nome: str, testo: str) -> None:
    """Salva un foglio accanto all'originale, senza fare drammi se non si
    puo': in quel caso resta il file intero, piu' pesante ma identico."""
    from pathlib import Path
    try:
        css = Path(__file__).parent / "static" / "css"
        destinazione = css / nome
        if destinazione.exists() and destinazione.read_text(encoding="utf-8") == testo:
            return
        provvisorio = destinazione.with_suffix(".tmp")
        provvisorio.write_text(testo, encoding="utf-8")
        provvisorio.replace(destinazione)
    except OSError:
        pass


def _foglio_di_stile() -> str:
    """Indirizzo del foglio da collegare al sito pubblico."""
    from pathlib import Path
    _parte_pubblica()             # garantisce che i file esistano
    css = Path(__file__).parent / "static" / "css"
    if (css / "style-pubblico.min.css").exists():
        return _asset("/static/css/style-pubblico.min.css")
    if (css / "style.min.css").exists():
        return _asset("/static/css/style.min.css")
    return _asset("/static/css/style.css")


def _foglio_intero() -> str:
    """Indirizzo del foglio completo: lo usa solo il pannello."""
    from pathlib import Path
    _stile_incorporato()
    css = Path(__file__).parent / "static" / "css"
    if (css / "style.min.css").exists():
        return _asset("/static/css/style.min.css")
    return _asset("/static/css/style.css")


templates.env.globals["stile_incorporato"] = _parte_pubblica
templates.env.globals["foglio_di_stile"] = _foglio_di_stile
templates.env.globals["foglio_intero"] = _foglio_intero
