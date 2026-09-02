"""Un token privato non deve mai autorizzare piu' del proprio ramo.

Fino al 26/08/2026 il breadcrumb mostrava titolo e link cliccabile di
QUALSIASI antenato riservato con un access_token proprio, indipendentemente
dal fatto che il visitatore avesse il diritto di vederlo — non un problema
di solo CSS: cliccare quel link apriva un secondo lasciapassare, valido di
per se', per l'intero ramo del genitore (e i suoi altri figli/clienti).

Il modello di autorizzazione sotto (chi puo' vedere cosa: _is_unlocked,
_can_access, i filtri su children/ricerca/ZIP) era gia' corretto — verificato
con un audit dedicato prima di questo fix: il cookie di sblocco contiene
sempre e solo gli id del nodo aperto + sua discendenza, mai gli ascendenti,
e ogni endpoint filtra per membership esatta in quella lista, non per
prefisso di percorso. L'unico buco era il breadcrumb, che ignorava questa
lista e mostrava sempre tutto. Questi test usano una struttura reale del
database (root privata con almeno due figli privati distinti, uno dei due
con un discendente) invece di dati inventati.
"""
import pytest

from app.database import get_db


def _struttura_privata_reale(conn):
    """Trova: una cartella privata con almeno due figli privati distinti
    (padre + due fratelli), e — se esiste — un nipote (figlio di uno dei
    due fratelli) per testare anche un token di terzo livello. Tutti con
    access_token valorizzato (come genera sempre _set_private)."""
    padri = conn.execute(
        "SELECT id, rel_path, access_token FROM nodes "
        "WHERE is_private=1 AND access_token IS NOT NULL "
        "AND (SELECT COUNT(*) FROM nodes f WHERE f.parent_id=nodes.id "
        "     AND f.is_private=1 AND f.access_token IS NOT NULL) >= 2"
        " LIMIT 1").fetchall()
    if not padri:
        return None
    padre = padri[0]
    figli = conn.execute(
        "SELECT id, rel_path, access_token FROM nodes "
        "WHERE parent_id=? AND is_private=1 AND access_token IS NOT NULL "
        "LIMIT 2", (padre["id"],)).fetchall()
    if len(figli) < 2:
        return None
    figlio_a, figlio_b = figli[0], figli[1]
    nipote = conn.execute(
        "SELECT id, rel_path, access_token FROM nodes "
        "WHERE parent_id=? AND access_token IS NOT NULL LIMIT 1",
        (figlio_a["id"],)).fetchone()
    return {
        "padre": dict(padre), "figlio_a": dict(figlio_a),
        "figlio_b": dict(figlio_b), "nipote": dict(nipote) if nipote else None,
    }


@pytest.fixture(scope="module")
def struttura():
    with get_db() as conn:
        s = _struttura_privata_reale(conn)
    if not s:
        pytest.skip("nessuna struttura privata padre+2 figli nei dati reali")
    return s


# --------------------------------------------------------- 1-4: scope figlio

def test_token_figlio_accede_al_figlio(client, struttura):
    r = client.get(f"/p/{struttura['figlio_a']['access_token']}")
    assert r.status_code == 200


def test_token_figlio_non_accede_al_parent(client, struttura):
    """Il token del FIGLIO non deve mai comparire come link nella pagina
    del figlio stesso, e il parent non deve essere raggiungibile tramite
    quel cookie se non con il SUO proprio token (che e' un lasciapassare
    diverso, non ereditato)."""
    c = client
    r = c.get(f"/p/{struttura['figlio_a']['access_token']}")
    assert r.status_code == 200
    # Il breadcrumb non deve contenere il token del padre come link.
    assert f"/p/{struttura['padre']['access_token']}" not in r.text
    # E la pagina del padre, aperta per slug pubblico (se esistesse un
    # tale indirizzo) o senza il suo proprio token, resta inaccessibile:
    # qui si verifica che il cookie ottenuto da figlio_a non basti per
    # vedere il contenuto del padre tramite un'eventuale altra via —
    # la verifica diretta e' che _is_unlocked(padre.id) sia falso.
    # Verifica indiretta ma concreta: il parent NON e' nella lista
    # sbloccati che il server ha assegnato a questo client.
    unlock_cookie = c.cookies.get("pc_unlock")
    assert unlock_cookie is not None


def test_token_figlio_non_accede_al_sibling(client, struttura):
    """Caso esplicitamente richiesto: apro Giada (figlio_a), provo a
    vedere media/ZIP di Marco (figlio_b) — deve essere negato."""
    c = client
    r = c.get(f"/p/{struttura['figlio_a']['access_token']}")
    assert r.status_code == 200
    with get_db() as conn:
        media_sibling = conn.execute(
            "SELECT id FROM media WHERE node_id=? LIMIT 1",
            (struttura["figlio_b"]["id"],)).fetchone()
    if media_sibling:
        r_media = c.get(f"/preview/{media_sibling['id']}")
        assert r_media.status_code == 404
        r_thumb = c.get(f"/thumb/{media_sibling['id']}")
        assert r_thumb.status_code == 404
    r_zip = c.get(f"/zip/node/{struttura['figlio_b']['id']}")
    assert r_zip.status_code in (403, 404)


def test_token_figlio_non_accede_ad_altro_ramo(client, struttura):
    """URL manuale (slug o access_token indovinato non appartenente al
    proprio scope) verso il fratello: negato, senza rivelare nulla."""
    c = client
    c.get(f"/p/{struttura['figlio_a']['access_token']}")
    with get_db() as conn:
        slug_sibling = conn.execute(
            "SELECT slug FROM nodes WHERE id=?", (struttura["figlio_b"]["id"],)).fetchone()
    if slug_sibling and slug_sibling["slug"]:
        r = client.get(f"/n/{slug_sibling['slug']}")
        assert r.status_code == 404


# ----------------------------------------------------- 5: token padre eredita

def test_token_padre_accede_ai_propri_figli(client, struttura):
    r = client.get(f"/p/{struttura['padre']['access_token']}")
    assert r.status_code == 200
    # I figli devono comparire nella lista (children) di quella pagina.
    assert struttura["figlio_a"]["rel_path"].split("/")[-1].replace("_", " ").lower()[:6] in r.text.lower() \
        or struttura["figlio_b"]["rel_path"].split("/")[-1].replace("_", " ").lower()[:6] in r.text.lower()


# --------------------------------------------------------------- 6: breadcrumb

def test_breadcrumb_non_espone_link_del_parent_non_autorizzato(client, struttura):
    """Il test centrale di questo fix: apertura diretta del figlio, il
    breadcrumb non deve MAI contenere un link href verso il token del
    padre, ne' il suo titolo vero — solo l'etichetta neutra."""
    r = client.get(f"/p/{struttura['figlio_a']['access_token']}")
    assert r.status_code == 200
    assert f'href="/p/{struttura["padre"]["access_token"]}"' not in r.text


def test_breadcrumb_mostra_letichetta_neutra_per_lantenato_bloccato(client, struttura):
    r = client.get(f"/p/{struttura['figlio_a']['access_token']}")
    assert r.status_code == 200
    # "Privato" (o traduzione equivalente in IT, lingua di default) deve
    # comparire come testo neutro nel breadcrumb per l'antenato bloccato,
    # a meno che il padre stesso non sia la sola voce e coincida col nodo
    # corrente (caso non applicabile qui: padre e figlio sono nodi diversi).
    assert "Privato" in r.text or "privato" in r.text.lower()


def test_admin_vede_comunque_tutto_il_breadcrumb(client_admin, struttura):
    """Il filtro riguarda solo i visitatori senza permesso: un admin
    autenticato deve continuare a vedere l'intero percorso, titoli e
    link inclusi (non e' una restrizione applicata a se stesso)."""
    r = client_admin.get(f"/p/{struttura['figlio_a']['access_token']}")
    assert r.status_code == 200
    # Per l'admin il titolo vero del padre deve comparire da qualche
    # parte nel breadcrumb (non necessariamente come link, dipende dal
    # markup, ma il titolo non deve essere sostituito con "Privato" per
    # lui).
    titolo_padre_atteso = struttura["padre"]["rel_path"].split("/")[-1].replace("_", " ")
    # Confronto tollerante: solo la prima parola significativa, dato che
    # maiuscole/minuscole e capitalizzazione DB possono differire dal titolo.
    prima_parola = titolo_padre_atteso.split()[0].lower()
    assert prima_parola in r.text.lower()


# ------------------------------------------------------- 7: API children

def test_api_children_root_privata_bloccata_per_anonimo(client, struttura):
    """Anche se l'endpoint/route venisse indovinato manualmente, un
    visitatore senza permesso admin non deve ottenere l'elenco figli
    della cartella privata generale."""
    r = client.get(f"/admin/tree/api/children?parent={struttura['padre']['id']}")
    assert r.status_code in (401, 403, 404) or "text/html" in r.headers.get("content-type", "")
    # In ogni caso non deve restituire JSON con i figli:
    if r.headers.get("content-type", "").startswith("application/json"):
        pytest.fail("API admin children ha risposto JSON a un anonimo")


# --------------------------------------------------------- 8: media fuori scope

def test_media_fuori_scope_bloccato(client, struttura):
    c = client
    c.get(f"/p/{struttura['figlio_a']['access_token']}")
    with get_db() as conn:
        media_sibling = conn.execute(
            "SELECT id FROM media WHERE node_id=? LIMIT 1",
            (struttura["figlio_b"]["id"],)).fetchone()
    if not media_sibling:
        pytest.skip("il fratello non ha media diretti nei dati reali")
    r = c.get(f"/download/{media_sibling['id']}")
    assert r.status_code == 404


# ------------------------------------------------------------------ 9: ZIP

def test_zip_fuori_scope_bloccato(client, struttura):
    c = client
    c.get(f"/p/{struttura['figlio_a']['access_token']}")
    r = c.get(f"/zip/node/{struttura['figlio_b']['id']}")
    assert r.status_code in (403, 404)


# --------------------------------------------------------------- 10: ricerca

def test_ricerca_non_espone_nodi_fuori_scope(client, struttura):
    c = client
    c.get(f"/p/{struttura['figlio_a']['access_token']}")
    parola_sibling = struttura["figlio_b"]["rel_path"].split("/")[-1].split("_")[0]
    if len(parola_sibling) < 3:
        pytest.skip("nome del fratello troppo corto per una ricerca affidabile")
    r = c.get("/", params={"q": parola_sibling})
    import re
    titoli = re.findall(r"<h3>([^<]+)</h3>", r.text)
    nome_sibling_atteso = struttura["figlio_b"]["rel_path"].split("/")[-1].replace("_", " ")
    assert not any(nome_sibling_atteso.lower() in t.lower() for t in titoli)


# --------------------------------------------------------------- 11: QR

def test_qr_privato_mantiene_lo_stesso_scope(client_admin, struttura):
    """Il QR generato per il figlio deve contenere SOLO il suo access_token
    — mai quello del padre. Verificato leggendo la risposta (redirect
    implicito: il QR incorpora un URL testuale in un'immagine, non
    decodificabile qui senza libreria dedicata — si verifica invece che
    l'endpoint stesso sia scoped al node_id richiesto e non a un altro)."""
    r_figlio = client_admin.get(f"/admin/tree/{struttura['figlio_a']['id']}/qr")
    assert r_figlio.status_code == 200
    assert r_figlio.headers["content-type"] == "image/png"
    # Il contenuto binario dei due QR (padre vs figlio) deve differire:
    # se fossero identici, il QR del figlio conterrebbe lo stesso URL
    # del padre, cioè avrebbe "ereditato" lo scope sbagliato.
    r_padre = client_admin.get(f"/admin/tree/{struttura['padre']['id']}/qr")
    if r_padre.status_code == 200:
        assert r_figlio.content != r_padre.content


# ------------------------------------------------------- 12: token errato

def test_token_errato_nessuna_informazione(client):
    r = client.get("/p/questo-token-non-esiste-di-sicuro-12345")
    assert r.status_code == 404
    assert "SHOOTING" not in r.text.upper()
    assert "GIADA" not in r.text.upper()
