"""Che il sito regga a girare su piu' processi in parallelo.

Dal 17/08/2026 il sito gira su quattro processi invece di uno: cosi' una
richiesta che si mette a lavorare — generare un'anteprima costa quasi
settecento millisecondi — non occupa l'unica corsia disponibile lasciando
in coda chi arriva nel frattempo.

Il prezzo e' che nessuno stato puo' piu' vivere nella memoria di un
processo: le richieste di una stessa persona finiscono su processi
diversi, uno dopo l'altro. Questi test verificano che le due cose che ci
stavano — il conteggio dei tentativi di accesso e l'avanzamento della
lettura dei numeri — siano davvero condivise.
"""
import re
import subprocess
import sys
from pathlib import Path


RADICE = Path(__file__).resolve().parent.parent


def _in_un_altro_processo(codice: str) -> str:
    """Esegue del codice in un processo Python nuovo di zecca.

    E' l'unico modo onesto di provarlo: dentro lo stesso processo qualsiasi
    variabile in memoria sembrerebbe condivisa."""
    return subprocess.run(
        [sys.executable, "-c", f"import sys; sys.path.insert(0, {str(RADICE)!r})\n{codice}"],
        capture_output=True, text=True, timeout=60).stdout.strip()


def test_i_tentativi_di_accesso_sono_contati_una_volta_sola():
    """Con il conteggio in memoria, quattro processi avrebbero dato a chi
    prova a indovinare quattro volte i tentativi consentiti."""
    from app.security import RateLimiter
    contatore = RateLimiter("prova_test", max_attempts=3, window_seconds=60)
    contatore.reset("10.0.0.1")
    try:
        for _ in range(3):
            contatore.hit("10.0.0.1")
        assert not contatore.check("10.0.0.1"), "il limite non scatta nemmeno qui"

        risposta = _in_un_altro_processo(
            "from app.security import RateLimiter\n"
            "c = RateLimiter('prova_test', max_attempts=3, window_seconds=60)\n"
            "print('consentito' if c.check('10.0.0.1') else 'bloccato')")
        assert risposta == "bloccato", (
            "un processo appena avviato non vede i tentativi degli altri: "
            "il limite si moltiplicherebbe per il numero di processi")
    finally:
        contatore.reset("10.0.0.1")


def test_i_tentativi_sopravvivono_al_riavvio():
    """Prima stavano in memoria: bastava il riavvio notturno del servizio
    per ripulire la lavagna a chi stava provando."""
    from app.security import RateLimiter
    contatore = RateLimiter("prova_test", max_attempts=2, window_seconds=60)
    contatore.reset("10.0.0.2")
    try:
        contatore.hit("10.0.0.2")
        contatore.hit("10.0.0.2")
        rimasti = _in_un_altro_processo(
            "from app.security import RateLimiter\n"
            "print(RateLimiter('prova_test', max_attempts=2, window_seconds=60)"
            ".resta('10.0.0.2'))")
        assert rimasti == "0", f"un processo nuovo vede {rimasti} tentativi ancora liberi"
    finally:
        contatore.reset("10.0.0.2")


def test_avanzamento_della_lettura_numeri_leggibile_da_ogni_processo():
    """Chi fa partire la lettura e chi poi chiede "a che punto siamo" sono
    due richieste diverse, e possono finire su processi diversi. Con
    l'avanzamento in memoria il pannello avrebbe mostrato "nessun lavoro in
    corso" mentre il lavoro girava accanto."""
    risposta = _in_un_altro_processo(
        "from app.ocr import stato_lavoro, lettura_in_corso\n"
        "s = stato_lavoro()\n"
        "print('ok' if isinstance(s, dict) and 'attivo' in s "
        "and isinstance(lettura_in_corso(), bool) else 'no')")
    assert risposta == "ok", "l'avanzamento non e' leggibile da un altro processo"


def test_nessuno_stato_nuovo_e_finito_in_memoria():
    """Guardia per il futuro: un contenitore modificabile a livello di
    modulo, in un sito su piu' processi, e' quasi sempre un errore. Le
    quattro eccezioni qui sotto sono deliberate e spiegate."""
    consentiti = {
        # Coda delle visite da scrivere: ogni processo scrive la sua, e il
        # totale e' la somma. Niente da condividere.
        ("app/database.py", "_coda_stat"),
        # Stessa coda, stesso motivo, ma per le statistiche per album
        # (node_stats): aperture e download bufferizzati prima di scrivere.
        ("app/database.py", "_coda_node_stat"),
        # Avanzamento della lettura numeri: e' anche su file, e il file e'
        # cio' che gli altri processi leggono (vedi ocr.stato_lavoro).
        ("app/ocr.py", "_stato"),
        # Copia in memoria del foglio di stile: ogni processo se la rilegge
        # dal disco da solo, e il disco e' uno.
        ("app/templating.py", "_cache_stile"),
    }
    trovati = set()
    for f in sorted((RADICE / "app").rglob("*.py")):
        rel = str(f.relative_to(RADICE))
        for riga in f.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^(_?[a-z][\w]*)\s*[:=].*(\{\}|\[\]|dict\(\)|list\(\)|set\(\))\s*$", riga)
            if m:
                trovati.add((rel, m.group(1)))
    nuovi = sorted(trovati - consentiti)
    assert not nuovi, (
        f"stato tenuto nella memoria di un processo solo: {nuovi}. "
        "Con piu' processi ognuno avrebbe il suo. Se e' voluto, aggiungilo "
        "all'elenco qui sopra con il motivo.")
