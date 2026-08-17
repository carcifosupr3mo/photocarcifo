"""Controlli sul progetto nel suo insieme, non sulle singole pagine.

Sono le cose che non si rompono oggi ma il giorno in cui si reinstalla, e
allora e' tardi: una libreria usata e mai dichiarata, un'impostazione che
il file di esempio non nomina, un file di configurazione con dentro un
segreto vero.
"""
import re
import sys
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent

ALIAS = {  # nome con cui si importa -> nome del pacchetto da installare
    "pil": "pillow",
    "argon2": "argon2-cffi",
    "zipstream": "zipstream-new",
    "pydantic_settings": "pydantic-settings",
    "rapidocr_onnxruntime": "rapidocr-onnxruntime",
}


def _librerie_usate() -> set:
    interne = {"app"} | {p.stem for p in (RADICE / "app").rglob("*.py")}
    trovate = set()
    for f in (RADICE / "app").rglob("*.py"):
        for m in re.finditer(r"^\s*(?:from|import)\s+([a-zA-Z_]\w*)",
                             f.read_text(encoding="utf-8"), re.M):
            nome = m.group(1)
            if nome not in sys.stdlib_module_names and nome not in interne \
                    and not nome.startswith("_"):
                trovate.add(nome)
    return trovate


def _librerie_dichiarate() -> set:
    dichiarate = set()
    for nome in ("requirements.txt", "requirements-ocr.txt"):
        for riga in (RADICE / nome).read_text(encoding="utf-8").splitlines():
            riga = riga.split("#")[0].strip()
            if riga:
                dichiarate.add(re.split(r"[=<>\[]", riga)[0].strip().lower())
    return dichiarate


def test_ogni_libreria_usata_e_dichiarata():
    """Il 17/08/2026 il file delle librerie non nominava pyotp, qrcode e
    zipstream: una reinstallazione da zero sarebbe partita senza verifica
    in due passaggi e senza scaricamento degli album, e il guasto si
    sarebbe visto solo usando quelle due cose."""
    dichiarate = _librerie_dichiarate()
    mancanti = sorted(n for n in _librerie_usate()
                      if ALIAS.get(n.lower(), n.lower()) not in dichiarate)
    assert not mancanti, (
        f"usate nel codice ma non in requirements: {mancanti}. "
        "Da qui il sito funziona (sono installate), ma reinstallandolo no.")


def test_il_file_di_esempio_nomina_tutte_le_impostazioni():
    """Chi rimonta il sito parte da .env.example: se non nomina
    un'impostazione, quella prende il valore predefinito in silenzio."""
    esempio = (RADICE / ".env.example").read_text(encoding="utf-8")
    nominate = set(re.findall(r"^\s*#?\s*([A-Z][A-Z0-9_]+)\s*=", esempio, re.M))
    from app.config import Settings
    attese = {c.upper() for c in Settings.model_fields}
    # secret_key e' l'unica che il file di esempio non deve contenere gia'
    # pronta: va generata da chi installa.
    mancanti = sorted(attese - nominate)
    assert not mancanti, f"impostazioni non documentate in .env.example: {mancanti}"


def test_nessun_segreto_vero_nel_file_di_esempio():
    esempio = (RADICE / ".env.example").read_text(encoding="utf-8")
    for riga in esempio.splitlines():
        if riga.strip().startswith("SECRET_KEY="):
            valore = riga.split("=", 1)[1].strip()
            assert len(valore) < 32 or not re.fullmatch(r"[0-9a-f]{32,}", valore), \
                "il file di esempio contiene una chiave che sembra vera"


def test_il_file_con_i_segreti_non_e_leggibile_da_tutti():
    env = RADICE / ".env"
    if not env.exists():
        return
    modo = env.stat().st_mode & 0o777
    assert modo & 0o077 == 0, (
        f".env ha permessi {oct(modo)}: lo puo' leggere anche chi non deve")


def test_niente_segreti_scritti_nel_codice():
    sospetti = []
    schema = re.compile(
        r"""(password|secret|token|api_?key)\s*=\s*["']([^"']{12,})["']""", re.I)
    for f in (RADICE / "app").rglob("*.py"):
        for n, riga in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            m = schema.search(riga)
            if not m:
                continue
            valore = m.group(2)
            # I nomi di campo, i percorsi e i testi non sono segreti.
            if valore.startswith(("/", "http", "{")) or " " in valore:
                continue
            sospetti.append(f"{f.name}:{n}")
    assert not sospetti, f"possibili segreti scritti nel codice: {sospetti}"


def test_il_database_ha_gli_indici_che_le_pagine_usano():
    """Senza un indice la pagina funziona lo stesso, solo lentamente: e' il
    tipo di peggioramento che non si nota finche' l'archivio non cresce."""
    from app.database import get_db
    attesi = {"idx_media_node", "idx_numeri_numero", "idx_numeri_media",
              "idx_nodes_parent", "idx_nodes_token", "idx_nodes_data"}
    with get_db() as conn:
        presenti = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'").fetchall()}
    mancanti = sorted(attesi - presenti)
    assert not mancanti, f"indici mancanti: {mancanti}"


def test_il_database_e_integro():
    from app.database import get_db
    with get_db() as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
