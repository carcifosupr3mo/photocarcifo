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
                   "/admin/raduni", "/admin/2fa", "/admin/logs",
                   "/admin/condivisioni"]


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


# --------------------------------------------------------------------
# Freno ai tentativi: login e verifica in due passaggi contano separati
# --------------------------------------------------------------------
# Fino al 25/08/2026 il codice a sei cifre e la password che disattiva la
# verifica usavano lo stesso contatore del login. Sbagliare il codice
# perche' l'orologio del telefono va indietro chiudeva fuori anche dal
# login, e viceversa: un fastidio vero per chi entra dal campo, senza
# nessun guadagno di sicurezza (sono due porte diverse).

def test_freni_login_e_totp_sono_separati():
    """I due contatori devono essere oggetti distinti con ambiti distinti,
    altrimenti un tentativo sbagliato sull'uno consuma anche l'altro."""
    from app.security import login_limiter, totp_limiter
    assert login_limiter is not totp_limiter
    assert login_limiter.ambito != totp_limiter.ambito
    assert totp_limiter.ambito == "totp"
    # Il freno deve restare: separato non vuol dire assente.
    assert totp_limiter.max_attempts > 0
    assert totp_limiter.window > 0


def test_un_tentativo_totp_non_consuma_il_freno_del_login(tmp_path, monkeypatch):
    """Scritto contro un database usa-e-getta: i test non toccano quello
    vero. Registra un tentativo fallito sull'ambito del codice e verifica
    che il conteggio del login resti a zero."""
    import sqlite3, time
    from app.security import RateLimiter
    percorso = tmp_path / "prova.db"
    conn = sqlite3.connect(percorso)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE tentativi (ambito TEXT, chiave TEXT, quando REAL)")
    conn.commit()

    login = RateLimiter("login", max_attempts=5)
    totp = RateLimiter("totp", max_attempts=5)
    chiave = "10.0.0.1"

    # cinque tentativi sbagliati sul codice: il freno del codice scatta...
    for _ in range(5):
        conn.execute("INSERT INTO tentativi VALUES(?,?,?)",
                     (totp.ambito, chiave, time.time()))
    conn.commit()
    assert totp._conta(conn, chiave) == 5
    # ...ma quello del login non ha visto niente.
    assert login._conta(conn, chiave) == 0
    conn.close()


def test_il_freno_dimentica_i_tentativi_vecchi(tmp_path):
    """La finestra e' scorrevole: un tentativo di mezz'ora fa non deve
    contare piu', altrimenti il blocco non scadrebbe mai."""
    import sqlite3, time
    from app.security import RateLimiter
    percorso = tmp_path / "prova.db"
    conn = sqlite3.connect(percorso)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE tentativi (ambito TEXT, chiave TEXT, quando REAL)")
    totp = RateLimiter("totp", max_attempts=5, window_seconds=300)
    vecchio = time.time() - 3600      # un'ora fa, fuori finestra
    recente = time.time() - 10        # dieci secondi fa, dentro
    conn.execute("INSERT INTO tentativi VALUES(?,?,?)", ("totp", "10.0.0.2", vecchio))
    conn.execute("INSERT INTO tentativi VALUES(?,?,?)", ("totp", "10.0.0.2", recente))
    conn.commit()
    assert totp._conta(conn, "10.0.0.2") == 1, "il tentativo vecchio conta ancora"
    conn.close()


# --------------------------------------------------------------------
# Copertina scelta a mano
# --------------------------------------------------------------------
# La fotografia di copertina si puo' scegliere dal pannello. Il controllo
# che conta e' che appartenga davvero all'album: una copertina presa da un
# altro album metterebbe in vetrina un'immagine che li' dentro non c'e', e
# in un album riservato la farebbe uscire allo scoperto.

def _album_con_foto(conn, quante=3):
    return conn.execute(
        "SELECT n.id FROM nodes n JOIN media m ON m.node_id=n.id "
        "GROUP BY n.id HAVING COUNT(m.id) >= ? LIMIT 1", (quante,)).fetchone()


def test_copertina_rifiuta_una_foto_di_un_altro_album(client_admin):
    """Il caso che conta: media_id esistente, ma di un altro album."""
    from app.database import get_db
    with get_db() as conn:
        a = _album_con_foto(conn)
        altro = conn.execute(
            "SELECT id FROM media WHERE node_id != ? LIMIT 1", (a["id"],)).fetchone()
        prima = conn.execute("SELECT cover_media_id FROM nodes WHERE id=?",
                             (a["id"],)).fetchone()["cover_media_id"]
    r = client_admin.get("/admin/tree")
    import re
    tok = re.search(r'id="csrf"[^>]*value="([^"]+)"', r.text)
    if not tok:
        import pytest; pytest.skip("campo di sicurezza non trovato nella pagina")
    risposta = client_admin.post(f"/admin/tree/{a['id']}/copertina",
                                 data={"csrf_token": tok.group(1),
                                       "media_id": str(altro["id"])})
    assert risposta.status_code == 400, "una foto di un altro album e' stata accettata"
    with get_db() as conn:
        dopo = conn.execute("SELECT cover_media_id FROM nodes WHERE id=?",
                            (a["id"],)).fetchone()["cover_media_id"]
    assert dopo == prima, "la copertina e' cambiata malgrado il rifiuto"


def test_copertina_rifiuta_un_identificativo_non_numerico(client_admin):
    from app.database import get_db
    import re
    with get_db() as conn:
        a = _album_con_foto(conn)
    r = client_admin.get("/admin/tree")
    tok = re.search(r'id="csrf"[^>]*value="([^"]+)"', r.text)
    if not tok:
        import pytest; pytest.skip("campo di sicurezza non trovato nella pagina")
    risposta = client_admin.post(f"/admin/tree/{a['id']}/copertina",
                                 data={"csrf_token": tok.group(1),
                                       "media_id": "abc"})
    assert risposta.status_code == 400


def test_copertina_senza_permessi_non_passa(client):
    """Senza sessione da amministratore la rotta non deve nemmeno provarci."""
    from app.database import get_db
    with get_db() as conn:
        a = _album_con_foto(conn)
    risposta = client.post(f"/admin/tree/{a['id']}/copertina",
                           data={"csrf_token": "qualsiasi", "media_id": "1"})
    assert risposta.status_code in (401, 403), \
        f"un anonimo ha ottenuto {risposta.status_code}"


def test_copertina_cancellata_ricade_su_quella_automatica():
    """Se la fotografia scelta sparisce, la vetrina non deve restare rotta:
    _cover deve tornare alla scelta automatica."""
    from app.database import get_db
    from app.routers.tree import _cover
    with get_db() as conn:
        a = _album_con_foto(conn)
        # nodo finto con una copertina che non esiste piu'
        finto = {"id": a["id"], "cover_media_id": 999999999, "rel_path": ""}
        scelta = _cover(conn, finto)
    assert scelta != 999999999, "la copertina inesistente e' stata restituita"


def test_copertina_rifiuta_foto_di_sottoalbero_nascosto_per_album_pubblico(client_admin):
    """Un album pubblico non puo' pescare la copertina da un sotto-album
    hidden/private annidato: chi visita la vetrina vedrebbe una fotografia
    che quel sotto-album tiene apposta fuori dagli elenchi pubblici.

    Usa la gerarchia reale BMX (pubblico) / BMX/2023, BMX/2024 (nascosti),
    se esiste ancora con questa forma; altrimenti cerca un'altra coppia
    genitore pubblico / discendente riservato nel database vero, a
    QUALSIASI profondita' (come fa davvero la rotta, con rel_path LIKE),
    senza inventare dati."""
    from app.database import get_db, sottoalbero_like
    import re
    with get_db() as conn:
        coppia = conn.execute("""
            SELECT genitore.id AS gid, genitore.rel_path AS grp, figlio.id AS fid
            FROM nodes genitore JOIN nodes figlio
              ON figlio.rel_path LIKE ? ESCAPE '\\'
            JOIN media m ON m.node_id = figlio.id
            WHERE genitore.parent_id IS NULL
              AND COALESCE(genitore.is_private,0)=0 AND COALESCE(genitore.hidden,0)=0
              AND (COALESCE(figlio.is_private,0)=1 OR COALESCE(figlio.hidden,0)=1)
            LIMIT 1""", (sottoalbero_like("BMX"),)).fetchone()
        if not coppia:
            # Non e' scontato che ci sia sempre un genitore SENZA parent
            # a fare da radice pubblica: si allarga a qualunque coppia,
            # cercando in tutto l'albero invece che solo sotto BMX.
            radici = conn.execute("""
                SELECT id, rel_path FROM nodes
                WHERE COALESCE(is_private,0)=0 AND COALESCE(hidden,0)=0""").fetchall()
            for radice in radici:
                trovato = conn.execute("""
                    SELECT figlio.id AS fid FROM nodes figlio
                    JOIN media m ON m.node_id = figlio.id
                    WHERE figlio.rel_path LIKE ? ESCAPE '\\'
                      AND (COALESCE(figlio.is_private,0)=1 OR COALESCE(figlio.hidden,0)=1)
                    LIMIT 1""", (sottoalbero_like(radice["rel_path"]),)).fetchone()
                if trovato:
                    coppia = {"gid": radice["id"], "fid": trovato["fid"]}
                    break
        if not coppia:
            import pytest
            pytest.skip("nessun sotto-album riservato dentro un album pubblico da testare")
        foto = conn.execute("SELECT id FROM media WHERE node_id=? LIMIT 1",
                            (coppia["fid"],)).fetchone()
        prima = conn.execute("SELECT cover_media_id FROM nodes WHERE id=?",
                             (coppia["gid"],)).fetchone()["cover_media_id"]

    r = client_admin.get("/admin/tree")
    tok = re.search(r'id="csrf"[^>]*value="([^"]+)"', r.text)
    if not tok:
        import pytest; pytest.skip("campo di sicurezza non trovato nella pagina")

    risposta = client_admin.post(f"/admin/tree/{coppia['gid']}/copertina",
                                 data={"csrf_token": tok.group(1),
                                       "media_id": str(foto["id"])})
    assert risposta.status_code == 400, \
        "una foto di un sotto-album riservato e' stata accettata per un album pubblico"
    with get_db() as conn:
        dopo = conn.execute("SELECT cover_media_id FROM nodes WHERE id=?",
                            (coppia["gid"],)).fetchone()["cover_media_id"]
    assert dopo == prima, "la copertina e' cambiata malgrado il rifiuto"


def test_copertina_accetta_foto_riservata_per_album_gia_riservato(client_admin):
    """Un album gia' nascosto o privato non ha nulla da nascondere ai suoi
    stessi sotto-album: non c'e' fuga di riservatezza da bloccare li'."""
    from app.database import get_db
    import re
    with get_db() as conn:
        riservato = conn.execute("""
            SELECT id FROM nodes n
            WHERE (COALESCE(is_private,0)=1 OR COALESCE(hidden,0)=1)
              AND EXISTS (SELECT 1 FROM media m WHERE m.node_id=n.id)
            LIMIT 1""").fetchone()
        if not riservato:
            import pytest
            pytest.skip("nessun album riservato con foto proprie da testare")
        foto = conn.execute("SELECT id FROM media WHERE node_id=? LIMIT 1",
                            (riservato["id"],)).fetchone()
        prima = conn.execute("SELECT cover_media_id FROM nodes WHERE id=?",
                             (riservato["id"],)).fetchone()["cover_media_id"]

    r = client_admin.get("/admin/tree")
    tok = re.search(r'id="csrf"[^>]*value="([^"]+)"', r.text)
    if not tok:
        import pytest; pytest.skip("campo di sicurezza non trovato nella pagina")

    risposta = client_admin.post(f"/admin/tree/{riservato['id']}/copertina",
                                 data={"csrf_token": tok.group(1),
                                       "media_id": str(foto["id"])})
    assert risposta.status_code == 200, \
        "una foto propria dell'album non e' stata accettata come sua copertina"

    # ripristino: e' l'unico dei nuovi test che scrive davvero.
    from app.database import get_db as _db
    with _db() as conn:
        conn.execute("UPDATE nodes SET cover_media_id=? WHERE id=?",
                     (prima, riservato["id"]))
    with _db() as conn:
        v = conn.execute("SELECT cover_media_id FROM nodes WHERE id=?",
                         (riservato["id"],)).fetchone()["cover_media_id"]
    assert v == prima, "il ripristino della copertina originale non e' riuscito"


# --------------------------------------------------------------------
# Elenco delle foto dirette di un album (per scegliere la copertina)
# --------------------------------------------------------------------

def test_api_media_senza_permessi_non_passa(client):
    """Stessa dependency di api/children e api/node: un anonimo viene
    rimandato al login, non riceve i dati."""
    from app.database import get_db
    with get_db() as conn:
        a = _album_con_foto(conn)
    risposta = client.get(f"/admin/tree/api/media?node={a['id']}",
                          follow_redirects=False)
    assert risposta.status_code in (302, 303, 401, 403), \
        f"un anonimo ha ottenuto {risposta.status_code}"


def test_api_media_nodo_inesistente(client_admin):
    risposta = client_admin.get("/admin/tree/api/media?node=999999999")
    assert risposta.status_code == 404


def test_api_media_restituisce_solo_foto_del_nodo_richiesto(client_admin):
    """Deve elencare le foto dirette dell'album richiesto e nessun'altra:
    non e' un endpoint pubblico, ma sbagliare album qui vorrebbe dire
    mostrare in vetrina una foto presa da un altro cliente."""
    from app.database import get_db
    with get_db() as conn:
        a = _album_con_foto(conn)
        proprie = {r["id"] for r in conn.execute(
            "SELECT id FROM media WHERE node_id=? AND kind='image'",
            (a["id"],)).fetchall()}
        altrove = conn.execute(
            "SELECT id FROM media WHERE node_id != ? LIMIT 1", (a["id"],)).fetchone()

    risposta = client_admin.get(f"/admin/tree/api/media?node={a['id']}")
    assert risposta.status_code == 200
    dati = risposta.json()
    ids = {m["id"] for m in dati}
    assert ids, "l'album scelto per il test non ha restituito foto"
    assert ids == proprie, "l'elenco non corrisponde esattamente alle foto dirette dell'album"
    if altrove:
        assert altrove["id"] not in ids, "una foto di un altro album e' comparsa nell'elenco"


# --------------------------------------------------------------------
# Biscottino dello ZIP: sicuro e legato al momento giusto
# --------------------------------------------------------------------

def _csrf_da_pagina(pagina_client):
    import re
    r = pagina_client.get("/admin/condivisioni")
    tok = re.search(r'id="csrf"[^>]*value="([^"]+)"', r.text)
    if not tok:
        pytest.skip("campo di sicurezza non trovato nella pagina")
    return tok.group(1)


def test_revoca_foto_singola_rende_il_link_404(client_admin, client, dati):
    """Crea un token di condivisione su una foto pubblica gia' esistente,
    verifica che funzioni, lo revoca e verifica il 404. Alla fine ripristina
    lo stato originale della riga (share_token com'era prima)."""
    from app.database import get_db
    media_id = dati["media_id"]
    if not media_id:
        pytest.skip("nessuna fotografia pubblica da testare")
    with get_db() as conn:
        prima = conn.execute("SELECT share_token, share_created_at FROM media WHERE id=?",
                             (media_id,)).fetchone()

    tok = _csrf_da_pagina(client_admin)
    r = client_admin.post(f"/admin/tree/media/{media_id}/share",
                          data={"csrf_token": tok})
    assert r.status_code == 200
    token = r.json()["share_token"]

    r_pub = client.get(f"/f/{token}")
    assert r_pub.status_code == 200, "il link appena creato non funziona"

    r2 = client_admin.post(f"/admin/tree/media/{media_id}/share/revoke",
                           data={"csrf_token": tok})
    assert r2.status_code == 200

    r_dopo = client.get(f"/f/{token}")
    assert r_dopo.status_code == 404, "il link revocato risponde ancora"

    with get_db() as conn:
        conn.execute("UPDATE media SET share_token=?, share_created_at=? WHERE id=?",
                     (prima["share_token"], prima["share_created_at"], media_id))


def test_revoca_selezione_rende_il_link_404(client_admin, client, dati):
    """Stesso controllo per il link di selezione multipla (/fs/{token}),
    che vive nella tabella condivisioni: qui la revoca cancella davvero la
    riga, quindi non c'e' nulla da ripristinare dopo."""
    media_id = dati["media_id"]
    if not media_id:
        pytest.skip("nessuna fotografia pubblica da testare")

    tok = _csrf_da_pagina(client_admin)
    r = client.post("/condividi/selezione", data={"ids": str(media_id)})
    assert r.status_code == 200
    corpo = r.json()
    token = corpo["share_token"]

    from app.database import get_db
    with get_db() as conn:
        riga = conn.execute("SELECT id FROM condivisioni WHERE token=?",
                            (token,)).fetchone()
    assert riga, "la condivisione appena creata non e' in tabella"

    r_pub = client.get(f"/fs/{token}")
    assert r_pub.status_code == 200, "il link appena creato non funziona"

    r2 = client_admin.post(f"/admin/tree/condivisioni/{riga['id']}/revoca",
                           data={"csrf_token": tok})
    assert r2.status_code == 200

    r_dopo = client.get(f"/fs/{token}")
    assert r_dopo.status_code == 404, "il link revocato risponde ancora"


def test_pagina_selezione_condivisa_ha_attributi_lightbox(client, dati):
    """/fs/{token} deve portare gli attributi data-id/data-preview su ogni
    .photo della griglia: senza di loro initLightbox() (app.js) non trova
    nulla su cui agganciarsi e la lightbox non si apre, pur essendo lo
    stesso componente gia' usato in node.html."""
    media_id = dati["media_id"]
    if not media_id:
        pytest.skip("nessuna fotografia pubblica da testare")

    r = client.post("/condividi/selezione", data={"ids": str(media_id)})
    assert r.status_code == 200
    token = r.json()["share_token"]

    r_pub = client.get(f"/fs/{token}")
    assert r_pub.status_code == 200
    assert f'data-id="{media_id}"' in r_pub.text
    assert f'data-preview="/fs/{token}/anteprima/{media_id}"' in r_pub.text


def test_revoca_selezione_senza_permessi_non_passa(client, dati):
    """Un anonimo non puo' revocare nulla: qui basta un id qualsiasi,
    l'accesso deve essere respinto prima ancora di guardare il database."""
    r = client.post("/admin/tree/condivisioni/1/revoca",
                    data={"csrf_token": "qualsiasi"})
    assert r.status_code in (401, 403), \
        f"un anonimo ha ottenuto {r.status_code}"


def test_revoca_selezione_senza_token_csrf_viene_respinta(client_admin, dati):
    """Stesso controllo, ma con sessione valida e token CSRF sbagliato:
    deve essere il CSRF a fermare la richiesta, non l'assenza di sessione."""
    media_id = dati["media_id"]
    if not media_id:
        pytest.skip("nessuna fotografia pubblica da testare")
    r = client_admin.post("/condividi/selezione", data={"ids": str(media_id)})
    assert r.status_code == 200
    token = r.json()["share_token"]

    from app.database import get_db
    with get_db() as conn:
        riga = conn.execute("SELECT id FROM condivisioni WHERE token=?",
                            (token,)).fetchone()

    r2 = client_admin.post(f"/admin/tree/condivisioni/{riga['id']}/revoca",
                           data={"csrf_token": "non-e-un-token-valido"})
    assert r2.status_code == 403, \
        f"un token CSRF sbagliato ha ottenuto {r2.status_code}"

    # ripulisce quanto creato da questo test, dato che il CSRF errato ha
    # correttamente impedito che la revoca lo facesse.
    with get_db() as conn:
        conn.execute("DELETE FROM condivisioni WHERE id=?", (riga["id"],))


def test_biscottino_zip_e_marcato_secure():
    """Il sito e' solo HTTPS: il biscottino di segnalazione non deve
    poter viaggiare su una connessione in chiaro."""
    from app.database import get_db
    with get_db() as conn:
        riga = conn.execute(
            "SELECT id FROM media WHERE kind='image' LIMIT 1").fetchone()
    from app.main import app
    from fastapi.testclient import TestClient
    c = TestClient(app, raise_server_exceptions=False)
    r = c.get(f"/zip/select?ids={riga['id']}&segnale=prova-test",
             follow_redirects=False)
    intestazione = r.headers.get("set-cookie", "")
    assert "pc_zip=" in intestazione, "il biscottino non e' stato scritto"
    assert "secure" in intestazione.lower(), \
        f"il biscottino non porta il segno Secure: {intestazione}"
    assert "samesite=lax" in intestazione.lower()
    assert "max-age=60" in intestazione.lower()


# --------------------------------------------------------------------
# Azione di massa sugli album (selezione multipla nel pannello)
# --------------------------------------------------------------------
# Le stesse quattro azioni (pubblico/privato/nascondi/mostra) che esistono
# gia' singolarmente, applicate in una sola richiesta a piu' nodi. La
# propagazione al sottoalbero e' la stessa funzione usata dagli endpoint
# singoli: qui si controlla solo che il bulk la richiami correttamente e
# che un id inesistente nella lista non fermi gli altri.

def _due_foglie(conn):
    """Due nodi senza figli, per non propagare gli stati di test su interi
    rami dell'albero reale."""
    righe = conn.execute(
        "SELECT id, rel_path, is_private, hidden FROM nodes n "
        "WHERE NOT EXISTS (SELECT 1 FROM nodes f WHERE f.parent_id=n.id) "
        "LIMIT 2").fetchall()
    return righe


def test_bulk_senza_permessi_non_passa(client):
    r = client.post("/admin/tree/bulk",
                    data={"csrf_token": "qualsiasi", "node_ids": "1", "azione": "nascondi"},
                    follow_redirects=False)
    assert r.status_code in (302, 303, 401, 403)


def test_bulk_senza_token_csrf_viene_respinto(client_admin):
    from app.database import get_db
    with get_db() as conn:
        nodi = _due_foglie(conn)
    if len(nodi) < 2:
        pytest.skip("non ci sono abbastanza album senza sottocartelle da testare")
    r = client_admin.post("/admin/tree/bulk",
                          data={"csrf_token": "non-e-un-token-valido",
                                "node_ids": str(nodi[0]["id"]), "azione": "nascondi"})
    assert r.status_code == 403


def test_bulk_applica_a_piu_nodi_e_ignora_id_inesistente(client_admin):
    """Applica 'nascondi' a due album reali insieme a un id inesistente
    nel mezzo, poi ripristina lo stato originale di entrambi."""
    from app.database import get_db
    with get_db() as conn:
        nodi = _due_foglie(conn)
    if len(nodi) < 2:
        pytest.skip("non ci sono abbastanza album senza sottocartelle da testare")
    a, b = nodi[0], nodi[1]

    # Ripristino garantito anche se un assert sotto fallisce: questo test
    # tocca due album veri (non fixture isolate).
    tok = _csrf_da_pagina(client_admin)
    lista = f"{a['id']},999999999,{b['id']}"
    try:
        r = client_admin.post("/admin/tree/bulk",
                              data={"csrf_token": tok, "node_ids": lista, "azione": "nascondi"})
        assert r.status_code == 200
        corpo = r.json()
        assert corpo["ok"] is True
        assert corpo["aggiornati"] == 2, \
            "l'id inesistente nella lista ha bloccato o gonfiato il conteggio"

        with get_db() as conn:
            dopo_a = conn.execute("SELECT hidden FROM nodes WHERE id=?", (a["id"],)).fetchone()
            dopo_b = conn.execute("SELECT hidden FROM nodes WHERE id=?", (b["id"],)).fetchone()
        assert dopo_a["hidden"] == 1
        assert dopo_b["hidden"] == 1
    finally:
        with get_db() as conn:
            conn.execute("UPDATE nodes SET hidden=? WHERE id=?", (a["hidden"], a["id"]))
            conn.execute("UPDATE nodes SET hidden=? WHERE id=?", (b["hidden"], b["id"]))
    with get_db() as conn:
        ripristinato_a = conn.execute("SELECT hidden FROM nodes WHERE id=?", (a["id"],)).fetchone()["hidden"]
        ripristinato_b = conn.execute("SELECT hidden FROM nodes WHERE id=?", (b["id"],)).fetchone()["hidden"]
    assert ripristinato_a == a["hidden"]
    assert ripristinato_b == b["hidden"]


def test_bulk_propaga_al_sottoalbero_come_lendpoint_singolo(client_admin):
    """L'azione bulk su un genitore con figli deve propagare lo stato al
    sottoalbero esattamente come /privacy sul singolo nodo: stessa query,
    stesso comportamento, qui verificato passando dal bulk."""
    from app.database import get_db, sottoalbero_like
    with get_db() as conn:
        genitore = conn.execute(
            "SELECT id, rel_path, is_private FROM nodes n "
            "WHERE EXISTS (SELECT 1 FROM nodes f WHERE f.parent_id=n.id) "
            "LIMIT 1").fetchone()
        if not genitore:
            pytest.skip("nessun album con sottocartelle da testare")
        # sottoalbero_like produce "rel_path/%": prende SOLO i figli, non
        # il genitore stesso (che non fa match col proprio "/%"). Il bulk
        # tocca anche il genitore: senza includerlo qui il ripristino nel
        # finally lo lasciava nello stato invertito per sempre — e' cosi'
        # che ATLETICA e' finita is_private=1 in produzione.
        stato_originale = conn.execute(
            "SELECT id, is_private FROM nodes WHERE id=? OR rel_path LIKE ? ESCAPE '\\'",
            (genitore["id"], sottoalbero_like(genitore["rel_path"]))).fetchall()

    # Il ripristino va garantito anche se un assert sotto fallisce: questo
    # test tocca un album vero (non un fixture isolata), e un fallimento a
    # meta' lasciava il sottoalbero nello stato temporaneo del test — visto
    # succedere per davvero su ATLETICA in produzione.
    tok = _csrf_da_pagina(client_admin)
    nuovo_stato = 0 if genitore["is_private"] else 1
    azione = "privato" if nuovo_stato == 1 else "pubblico"
    try:
        r = client_admin.post("/admin/tree/bulk",
                              data={"csrf_token": tok, "node_ids": str(genitore["id"]), "azione": azione})
        assert r.status_code == 200

        with get_db() as conn:
            figli = conn.execute(
                "SELECT is_private FROM nodes WHERE rel_path LIKE ? ESCAPE '\\'",
                (sottoalbero_like(genitore["rel_path"]),)).fetchall()
        assert all(f["is_private"] == nuovo_stato for f in figli), \
            "l'azione bulk non ha propagato lo stato al sottoalbero"
    finally:
        with get_db() as conn:
            for riga in stato_originale:
                conn.execute("UPDATE nodes SET is_private=? WHERE id=?",
                            (riga["is_private"], riga["id"]))
