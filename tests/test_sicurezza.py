"""Che le porte chiuse restino chiuse.

Sono i controlli che nessuno rifa' a mano dopo ogni modifica, ed e' proprio
per questo che ogni tanto si aprono senza che nessuno se ne accorga: una
rotta nuova copiata da una vecchia dimenticandosi il controllo dei
permessi, un album riservato che ricompare in un elenco.
"""
import inspect

import pytest


# --- Il pannello -----------------------------------------------------------

PAGINE_PANNELLO = ["/admin", "/admin/tree", "/admin/upload", "/admin/trash",
                   "/admin/recensioni", "/admin/ricerche", "/admin/preferite",
                   "/admin/raduni", "/admin/2fa", "/admin/logs"]


@pytest.mark.parametrize("percorso", PAGINE_PANNELLO)
def test_pannello_chiuso_a_chi_non_ha_fatto_accesso(client, percorso):
    r = client.get(percorso, follow_redirects=False)
    assert r.status_code in (302, 303, 307), f"{percorso} risponde {r.status_code}"
    assert "/admin/login" in r.headers.get("location", "")


@pytest.mark.parametrize("percorso", PAGINE_PANNELLO)
def test_pannello_aperto_a_chi_ha_fatto_accesso(client_admin, percorso):
    r = client_admin.get(percorso)
    assert r.status_code == 200, f"{percorso} risponde {r.status_code}"


# Le uniche due operazioni del pannello che non chiedono di aver gia' fatto
# accesso, e il perche'.
#
#   /admin/login   e' il posto dove l'accesso si fa: chiederlo qui sarebbe
#                  un cerchio chiuso. E' protetto dal conteggio dei
#                  tentativi, in security.py e in nginx.
#   /admin/logout  deve funzionare anche con una sessione gia' scaduta,
#                  altrimenti non si riuscirebbe a ripulire il browser. Il
#                  token viene comunque verificato quando una sessione c'e',
#                  quindi nessuno puo' far uscire un altro dal suo pannello.
SENZA_ACCESSO_PER_DISEGNO = {"/admin/login", "/admin/login/2fa", "/admin/logout"}


def test_ogni_operazione_del_pannello_ha_permessi_e_csrf(app):
    """Controllo strutturale: nessuna rotta che modifica dati puo' esistere
    senza verifica dei permessi e del token anti-falsificazione.

    E' il test che regge nel tempo: una rotta nuova copiata da una vecchia
    dimenticando il controllo lo fa fallire subito, mentre a mano una cosa
    del genere non la ricontrolla nessuno."""
    mancanti = []
    for rotta in app.routes:
        metodi = getattr(rotta, "methods", None)
        if not metodi or "POST" not in metodi:
            continue
        percorso = rotta.path
        if not percorso.startswith("/admin") or percorso in SENZA_ACCESSO_PER_DISEGNO:
            continue
        sorgente = inspect.getsource(rotta.endpoint)
        firma = str(inspect.signature(rotta.endpoint))
        if "require_admin" not in firma and "require_admin" not in sorgente:
            mancanti.append(f"{percorso}: nessun controllo dei permessi")
        if "csrf" not in sorgente.lower():
            mancanti.append(f"{percorso}: nessun controllo del token")
    assert not mancanti, "\n".join(mancanti)


def test_operazione_senza_token_viene_respinta(client_admin):
    r = client_admin.post("/admin/ricerche/svuota", data={})
    assert r.status_code in (403, 422), f"accettata senza token: {r.status_code}"


# --- Album riservati -------------------------------------------------------

def test_album_privato_non_raggiungibile_dall_indirizzo_pubblico(client, dati):
    if not dati["slug_privato"]:
        pytest.skip("nessun album privato")
    r = client.get(f"/n/{dati['slug_privato']}", headers={"accept": "text/html"})
    assert r.status_code == 404


def test_album_nascosto_non_raggiungibile(client, dati):
    if not dati["slug_nascosto"]:
        pytest.skip("nessun album nascosto")
    r = client.get(f"/n/{dati['slug_nascosto']}", headers={"accept": "text/html"})
    assert r.status_code == 404


def test_link_privato_ha_un_solo_indirizzo(client, dati):
    """Con il prefisso di lingua davanti non deve rispondere: un secondo
    indirizzo per un album riservato e' un secondo modo di ritrovarselo in
    giro."""
    if not dati["token_privato"]:
        pytest.skip("nessun album privato")
    assert client.get(f"/p/{dati['token_privato']}").status_code == 200
    assert client.get(f"/en/p/{dati['token_privato']}").status_code == 404


def test_link_privato_mostra_subito_il_contenuto(client, dati):
    """Alla prima apertura, non alla seconda: il lasciapassare viaggia
    insieme a questa stessa pagina, e per un periodo l'album fatto di sole
    sottocartelle risultava vuoto a chi apriva il link ricevuto."""
    if not dati["token_privato"]:
        pytest.skip("nessun album privato")
    r = client.get(f"/p/{dati['token_privato']}")
    assert r.status_code == 200
    assert "<img" in r.text, "album riservato vuoto alla prima apertura"


def test_foto_di_album_privato_non_servita_a_estranei(client, dati):
    if not dati["media_privato"]:
        pytest.skip("nessuna foto privata")
    for percorso in ("/thumb/", "/preview/", "/download/"):
        r = client.get(f"{percorso}{dati['media_privato']}")
        assert r.status_code == 404, f"{percorso} ha servito una foto riservata"


def test_zip_non_impacchetta_foto_riservate(client, dati):
    if not dati["media_privato"]:
        pytest.skip("nessuna foto privata")
    r = client.get(f"/zip/select?ids={dati['media_privato']}")
    assert r.status_code == 403


# --- Percorsi e ingressi ---------------------------------------------------

@pytest.mark.parametrize("cattivo", [
    "../../etc/passwd", "..%2f..%2fetc%2fpasswd", "%2e%2e/%2e%2e/etc/passwd",
])
def test_niente_risalita_di_cartelle(client, cattivo):
    r = client.get(f"/n/{cattivo}", headers={"accept": "text/html"})
    assert r.status_code in (400, 404), f"risposta inattesa: {r.status_code}"
    assert "root:" not in r.text


def test_intestazioni_di_sicurezza(client):
    r = client.get("/", headers={"accept": "text/html"})
    csp = r.headers.get("content-security-policy", "")
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp, "script scritti nella pagina sarebbero permessi"
    assert "frame-ancestors 'none'" in csp


def test_pannello_non_indicizzabile(client_admin):
    r = client_admin.get("/admin")
    assert "noindex" in r.text


def test_errori_non_mostrano_dettagli_interni(client):
    """Un indirizzo malformato dava in faccia i nomi dei parametri e i tipi
    attesi. A chi guarda non dice niente, a chi cerca punti deboli dice
    troppo."""
    r = client.get("/thumb/abc", headers={"accept": "text/html"})
    assert r.status_code == 400
    for parola in ("int_parsing", "traceback", "File \"", "media_id"):
        assert parola not in r.text, f"la pagina di errore contiene '{parola}'"


def test_le_pagine_dicono_sempre_da_cosa_dipendono(client, dati):
    """La pagina esce in due forme a seconda del biscotto del foglio di
    stile. Se non lo dichiara, una cache puo' servire la forma sbagliata.
    Prima la riga c'era solo sulla prima visita: proprio la forma piu'
    comune — quella di chi torna — usciva senza."""
    for biscotti in ({}, {"pc_css": "1"}):
        c = client
        r = c.get("/", cookies=biscotti) if biscotti else c.get("/")
        vary = r.headers.get("vary", "").lower()
        assert "cookie" in vary, f"manca Vary: Cookie con biscotti={biscotti}"


def test_le_pagine_non_si_tengono_da_parte(client):
    """Senza una regola esplicita ogni browser decide per conto suo quanto
    tenersi una pagina, e chi torna puo' non vedere per giorni le
    fotografie appena pubblicate."""
    r = client.get("/")
    cc = r.headers.get("cache-control", "").lower()
    assert "no-cache" in cc or "max-age=0" in cc, \
        f"le pagine non dicono per quanto valgono: {cc!r}"
    assert "public" not in cc, \
        "una pagina che cambia con l'accesso non va data in pasto alle cache condivise"


def test_nessun_album_espone_quello_che_il_genitore_nasconde():
    """Una cartella nuova dentro un album nascosto o riservato deve nascere
    protetta come lui.

    Il 22/08/2026, dividendo tre album in FOTO/ e VIDEO/, le due cartelle
    nate dentro un album nascosto sono nate visibili: 48 fotografie tolte
    dal sito di proposito erano tornate raggiungibili da chiunque. Nessuno
    se ne sarebbe accorto finche' qualcuno non ci fosse arrivato."""
    from app.database import get_db
    with get_db() as conn:
        nodi = {r["id"]: dict(r) for r in conn.execute(
            "SELECT id, parent_id, rel_path, hidden, is_private FROM nodes")}
    buchi = []
    for n in nodi.values():
        p = nodi.get(n["parent_id"])
        while p:
            if p["hidden"] and not n["hidden"]:
                buchi.append(f"{n['rel_path']} visibile dentro {p['rel_path']} nascosto")
                break
            if p["is_private"] and not n["is_private"]:
                buchi.append(f"{n['rel_path']} pubblico dentro {p['rel_path']} riservato")
                break
            p = nodi.get(p["parent_id"])
    assert not buchi, "protezione non ereditata:\n  " + "\n  ".join(buchi[:10])
