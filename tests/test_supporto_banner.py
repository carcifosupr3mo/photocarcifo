"""Test mirati: banner di supporto volontario (TWINT/IBAN) e rimozione
completa della precedente feature "vendita foto" (mai attivata, l'utente
ha cambiato idea: foto gratis come prima, nessun paywall)."""
import re


def test_pagina_pubblica_contiene_script_supporto(client, dati):
    assert dati["slug"], "serve un album pubblico nel DB di test"
    r = client.get(f"/n/{dati['slug']}")
    assert r.status_code == 200
    assert "supporto-banner.js" in r.text


def test_blocco_pcsupporto_presente_con_twint_configurato(client):
    r = client.get("/")
    assert r.status_code == 200
    m = re.search(r'<script id="pcSupporto"[^>]*>(.*?)</script>', r.text)
    assert m, "blocco #pcSupporto non trovato in home"
    import json
    dati_json = json.loads(m.group(1))
    assert "twint" in dati_json
    assert "iban" in dati_json


def test_numero_twint_configurato_correttamente(client):
    """Il numero TWINT deve essere quello reale fornito, non un placeholder
    inventato: verificato leggendo la configurazione effettiva, non un
    valore hardcoded nel test (se cambia in futuro il test lo segue)."""
    from app.config import get_settings
    numero = get_settings().twint_support_number
    assert numero, "TWINT_SUPPORT_NUMBER non configurato in .env"
    r = client.get("/")
    m = re.search(r'<script id="pcSupporto"[^>]*>(.*?)</script>', r.text)
    import json
    dati_json = json.loads(m.group(1))
    assert dati_json["twint"] == numero


def test_nessun_riferimento_a_vendita_foto_nella_pagina_pubblica(client, dati):
    """La feature vendita foto e' stata rimossa: nessuna traccia deve
    comparire pubblicamente (bottone, attributi data-sales, testo)."""
    assert dati["slug"]
    r = client.get(f"/n/{dati['slug']}")
    assert "data-sales" in r.text is False or "data-sales" not in r.text
    assert "data-price-cents" not in r.text
    assert "acquista_foto" not in r.text.lower()


def test_endpoint_vendita_non_esiste_piu(client_admin):
    """L'endpoint POST /admin/tree/{id}/vendita non deve piu' rispondere:
    o 404 (rotta rimossa) o comunque non deve accettare la richiesta."""
    from app.database import get_db
    with get_db() as conn:
        n = conn.execute("SELECT id FROM nodes LIMIT 1").fetchone()
    r = client_admin.post(f"/admin/tree/{n['id']}/vendita",
                          data={"csrf_token": "x", "sales_enabled": "1"})
    assert r.status_code == 404


def test_colonne_db_sales_esistono_ma_inutilizzate(client):
    """Le colonne restano nello schema (nessuna migrazione distruttiva),
    ma nessun album deve avere la vendita attiva: e' stata rimossa la
    UI per attivarla, il valore residuo deve restare a 0 ovunque."""
    from app.database import get_db
    with get_db() as conn:
        r = conn.execute(
            "SELECT COUNT(*) c FROM nodes WHERE sales_enabled=1").fetchone()
    assert r["c"] == 0


def test_sito_normale_invariato_pagine_pubbliche_rispondono(client):
    for percorso in ["/", "/radunimoto", "/privacy"]:
        r = client.get(percorso)
        assert r.status_code == 200, f"{percorso} non risponde 200"


def test_traduzioni_supporto_presenti_5_lingue():
    from app import lingue
    chiavi = ["js.supporto_titolo", "js.supporto_testo",
              "js.supporto_twint_label", "js.supporto_iban_label",
              "js.supporto_causale_label", "js.supporto_causale_valore",
              "js.supporto_twint_copiato", "js.supporto_iban_copiato",
              "js.supporto_chiudi", "js.supporto_chiudi_frase", "js.supporto_copia_aria"]
    for chiave in chiavi:
        assert chiave in lingue.TESTI, f"chiave mancante: {chiave}"
        for lang in ("it", "en", "fr", "de", "es"):
            assert lingue.TESTI[chiave].get(lang), \
                f"{chiave} manca la lingua {lang}"


def test_causale_e_sempre_foto_in_ogni_lingua():
    from app import lingue
    for lang in ("it", "en", "fr", "de", "es"):
        assert lingue.traduci("js.supporto_causale_valore", lang) == "Foto"
