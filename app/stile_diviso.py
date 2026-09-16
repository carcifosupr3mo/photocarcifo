"""Divide il foglio di stile in due: quello che serve a tutti e quello del pannello.

Il foglio e' uno solo perche' e' comodo da mantenere, ma un quarto delle sue
regole riguarda il pannello di amministrazione — schede degli album, albero
delle cartelle, caricamento, cestino — e quel quarto veniva spedito a ogni
visitatore che apriva la pagina iniziale. Venti chilobyte per disegnare cose
che non vedra' mai.

La divisione e' volutamente sbilanciata: al pannello va TUTTO, al pubblico va
tutto tranne cio' che risulta usato solo dal pannello. Cosi' un errore di
classificazione puo' solo togliere una regola al sito pubblico, mai al
pannello — e quel caso lo prende il test, che apre ogni pagina pubblica e
controlla che ogni classe che usa esista ancora nel foglio ridotto.
"""
import re
from pathlib import Path

RADICE = Path(__file__).parent


def _classi_del_pannello() -> set[str]:
    """Le classi che compaiono solo nei modelli e negli script del pannello."""
    def classi_in(percorsi):
        trovate = set()
        for f in percorsi:
            if not f.is_file():
                continue
            testo = f.read_text(encoding="utf-8", errors="replace")
            for gruppo in re.findall(r'class=["\']([^"\']+)["\']', testo):
                trovate.update(gruppo.split())
            # classi costruite dal codice: "acard-" + qualcosa
            for nome in re.findall(r'["\']([a-z][\w-]{2,})["\']', testo):
                trovate.add(nome)
        return trovate

    modelli = RADICE / "templates"
    statici = RADICE / "static" / "js"
    pannello = classi_in(list((modelli / "admin").rglob("*.html"))
                         + list(statici.glob("admin-*.js")))
    pubbliche = classi_in([f for f in modelli.rglob("*.html")
                           if "admin" not in f.parts]
                          + [f for f in statici.glob("*.js")
                             if not f.name.startswith("admin-")])
    return pannello - pubbliche


def _divide(css: str, solo_pannello: set[str]) -> tuple[str, str]:
    """Restituisce (pubblico, pannello) mantenendo le @media al loro posto."""
    def del_pannello(selettore: str) -> bool:
        classi = set(re.findall(r"\.([a-zA-Z][\w-]*)", selettore))
        # Senza classi (elementi, :root, *) resta pubblico: sono le fondamenta.
        return bool(classi) and classi <= solo_pannello

    pubblico, pannello = [], []
    i, n = 0, len(css)
    while i < n:
        apertura = css.find("{", i)
        if apertura == -1:
            pubblico.append(css[i:]); break
        testa = css[i:apertura]
        if "@media" in testa or "@supports" in testa:
            # blocco annidato: si divide il contenuto e si riavvolge
            profondita, j = 1, apertura + 1
            while j < n and profondita:
                if css[j] == "{": profondita += 1
                elif css[j] == "}": profondita -= 1
                j += 1
            dentro_pub, dentro_adm = _divide(css[apertura + 1:j - 1], solo_pannello)
            if dentro_pub.strip():
                pubblico.append(f"{testa}{{{dentro_pub}}}")
            if dentro_adm.strip():
                pannello.append(f"{testa}{{{dentro_adm}}}")
            i = j
            continue
        chiusura = css.find("}", apertura)
        if chiusura == -1:
            pubblico.append(css[i:]); break
        regola = css[i:chiusura + 1]
        (pannello if del_pannello(testa) else pubblico).append(regola)
        i = chiusura + 1
    return "".join(pubblico), "".join(pannello)


def dividi(css_ridotto: str) -> tuple[str, str]:
    """Il foglio gia' ridotto, diviso in (pubblico, aggiunta per il pannello)."""
    return _divide(css_ridotto, _classi_del_pannello())
