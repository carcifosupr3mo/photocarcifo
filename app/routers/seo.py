"""Router SEO: robots.txt, sitemap.xml e sitemap delle immagini.

Nella sitemap finiscono solo le cartelle pubbliche e visibili. La sitemap
delle immagini elenca le fotografie con didascalia e titolo, cosi' Google
Immagini puo' indicizzarle: per un fotografo e' il canale che porta piu'
visite.
"""
from xml.sax.saxutils import escape

from fastapi import APIRouter, HTTPException, Response

from .. import lingue
from ..config import get_settings
from ..database import get_db, MAX_SQLITE_INT
from .tree import _ultime_gallerie

router = APIRouter()

IMG_PER_SITEMAP = 1000


@router.get("/robots.txt", response_class=Response)
def robots():
    settings = get_settings()
    base = settings.site_url.rstrip("/")
    # Ai motori di ricerca si lasciano leggere soltanto le pagine che hanno
    # senso nei risultati: la pagina iniziale e gli album pubblici. Tutto il
    # resto (pannello, link riservati, scaricamenti, ricerche, cambio lingua)
    # non e' contenuto da mostrare, e lasciarlo aperto significava solo
    # riempire il rapporto di Search Console di segnalazioni.
    # Le stesse pagine esistono anche sotto /en/, /fr/, /de/ e /es/: se qui
    # si scrivesse solo "Disallow: /search", la versione inglese della
    # ricerca resterebbe aperta e tornerebbero le segnalazioni di Search
    # Console che avevamo appena chiuso.
    # "/radunimoto" e' uscito da questa lista il 02/09/2026 (commit
    # e0f2cbf): prima era protetta da un gate domanda/risposta mai
    # collegato dal sito, ora e' una pagina pubblica vera raggiungibile
    # dalla barra di navigazione, con contenuto proprio (eventi + album
    # pubblici collegati) — bloccarla ai motori di ricerca non aveva piu'
    # motivo, restava solo perche' nessuno l'aveva tolta. Trovato con un
    # audit Lighthouse SEO (is-crawlable) sulla pagina reale.
    chiusi = ["/admin", "/p/", "/download/", "/zip/", "/video/", "/search",
              "/preferiti/", "/mie-preferite", "/lingua/", "/healthz"]
    righe = ["User-agent: *"]
    for voce in chiusi:
        righe.append(f"Disallow: {voce}")
        for codice in lingue.PREFISSI:
            righe.append(f"Disallow: /{codice}{voce}")
    # I quattro ordinamenti danno la stessa pagina in sequenza diversa:
    # quattro copie da far scartare una per una. "/search" stesso e' solo
    # un rimando storico (redirect 302 verso "/", vedi tree.py:search): i
    # risultati veri vivono su "/?q=..." con lo stesso meccanismo, stessa
    # ragione per non farli indicizzare uno per uno.
    righe += ["Disallow: /*?ordine=", "Disallow: /*?q=", "Allow: /"]

    # Raccoglitori che prendono e non portano nessuno: strumenti di analisi
    # commerciale e raccolte di immagini per addestrare modelli. Il 17/08/2026
    # uno di questi ha seguito il collegamento "scarica tutto l'album" e si
    # e' portato via 4,8 GB in tre richieste.
    #
    # Questo e' il cartello sulla porta: vale per chi le regole le rispetta.
    # Chi non le rispetta lo ferma nginx, in
    # snippets/photocarcifo-automi.conf, che risponde "vietato" e basta.
    for automa in ("AhrefsBot", "SemrushBot", "MJ12bot", "DotBot", "BLEXBot",
                   "DataForSeoBot", "PetalBot", "Amazonbot", "Bytespider",
                   "GPTBot", "OAI-SearchBot", "ChatGPT-User", "CCBot",
                   "ClaudeBot", "anthropic-ai", "meta-externalagent",
                   "ImagesiftBot", "Diffbot", "omgili"):
        righe += ["", f"User-agent: {automa}", "Disallow: /"]

    righe += ["", f"Sitemap: {base}/sitemap.xml",
              f"Sitemap: {base}/sitemap-immagini.xml"]
    body = "\n".join(righe) + "\n"
    return Response(content=body, media_type="text/plain")


@router.get("/{chiave}.txt", response_class=Response)
def indexnow_key(chiave: str):
    """Verifica della chiave IndexNow (vedi app/indexnow.py).

    Lo standard richiede un file raggiungibile su /<chiave>.txt che
    risponda con la chiave stessa in testo semplice: e' cosi' che Bing (e
    gli altri motori che aderiscono al protocollo) si accertano che chi
    manda le notifiche sia davvero il proprietario del sito.

    La route e' generica (qualunque /<qualcosa>.txt) ma risponde solo se
    "chiave" combacia esattamente con quella configurata: qualunque altro
    indirizzo che finisce per ".txt" continua a dare 404 come prima,
    nessun nuovo modo di scoprire pagine che non esistono.
    """
    attesa = get_settings().indexnow_key.strip()
    if not attesa or chiave != attesa:
        raise HTTPException(status_code=404)
    return Response(content=attesa, media_type="text/plain")


@router.get("/novita.xml", response_class=Response)
def feed_novita():
    """Notifica delle gallerie nuove, in formato RSS.

    Serve a chi vuole sapere quando escono fotografie nuove senza dover
    ricontrollare il sito a mano. Non essendoci ne' contatti ne' iscrizioni
    via posta, questo e' l'unico canale di avviso che il sito puo' offrire,
    e non chiede niente in cambio: nessun indirizzo, nessuna registrazione.
    Si incolla in un lettore di feed e basta.
    """
    settings = get_settings()
    base = settings.site_url.rstrip("/")
    with get_db() as conn:
        gallerie = _ultime_gallerie(conn)

    voci = []
    for g in gallerie:
        indirizzo = f"{base}/n/{g['slug']}"
        dove = f"{g['dove']} — " if g["dove"] else ""
        descrizione = f"{dove}{g['total_media']} fotografie"
        # RFC 822: il formato delle date che i lettori di feed si aspettano.
        # Va scritto in inglese a prescindere dalla lingua del sistema.
        data = ""
        if g["quando"]:
            giorni = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
            mesi = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
                    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
            q = g["quando"]
            data = (f"<pubDate>{giorni[q.weekday()]}, {q.day:02d} "
                    f"{mesi[q.month - 1]} {q.year} "
                    f"{q.hour:02d}:{q.minute:02d}:{q.second:02d} +0000</pubDate>")
        immagine = ""
        if g["cover"]:
            # enclosure: i lettori di feed mostrano cosi' l'anteprima.
            immagine = (f'<enclosure url="{base}/social/{g["cover"]}" '
                        f'type="image/jpeg" length="0"/>')
        voci.append(
            "    <item>"
            f"<title>{escape(g['title'])}</title>"
            f"<link>{indirizzo}</link>"
            f"<guid isPermaLink=\"true\">{indirizzo}</guid>"
            f"<description>{escape(descrizione)}</description>"
            f"{data}{immagine}</item>")

    corpo = ('<?xml version="1.0" encoding="UTF-8"?>\n'
             '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
             '  <channel>\n'
             f"    <title>{escape(settings.site_name)} — ultime gallerie</title>\n"
             f"    <link>{base}/novita</link>\n"
             f'    <atom:link href="{base}/novita.xml" rel="self" type="application/rss+xml"/>\n'
             "    <description>Le fotografie pubblicate piu' di recente.</description>\n"
             "    <language>it</language>\n"
             + "\n".join(voci) + "\n"
             "  </channel>\n</rss>")
    return Response(content=corpo, media_type="application/rss+xml")


@router.get("/sitemap.xml", response_class=Response)
def sitemap():
    settings = get_settings()
    base = settings.site_url.rstrip("/")
    with get_db() as conn:
        # Niente piu' bisogno di contare le foto per album (COUNT/JOIN su
        # media): serviva solo a calcolare quante pagine ?page=N elencare,
        # e quelle voci non si generano piu' — vedi il commento piu' sotto.
        rows = conn.execute(
            "SELECT slug, updated_at FROM nodes "
            "WHERE is_private=0 AND hidden=0 "
            "ORDER BY depth, sort_order").fetchall()
    def voce(percorso: str, extra: str = "") -> str:
        """Una pagina, con l'elenco delle sue versioni nelle altre lingue.

        I tag xhtml:link fanno qui lo stesso lavoro che gli hreflang fanno
        nella testa della pagina: dicono che questi cinque indirizzi non
        sono doppioni ma la stessa cosa in lingue diverse. Scriverli anche
        qui evita che Google debba prima scaricare tutte le pagine per
        scoprirlo.
        """
        alternative = "".join(
            f'<xhtml:link rel="alternate" hreflang="{c}" '
            f'href="{base}{lingue.con_prefisso(percorso, c)}"/>'
            for c in lingue.CODICI)
        alternative += (f'<xhtml:link rel="alternate" hreflang="x-default" '
                        f'href="{base}{percorso}"/>')
        return f"  <url><loc>{base}{percorso}</loc>{extra}{alternative}</url>"

    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'
             ' xmlns:xhtml="http://www.w3.org/1999/xhtml">',
             voce("/", "<priority>1.0</priority>"),
             # Pagine fisse: senza elencarle qui i motori di ricerca le
             # trovano solo seguendo i collegamenti del menu, e piu' tardi.
             voce("/chi-sono", "<priority>0.8</priority>"),
             voce("/novita", "<priority>0.7</priority>"),
             voce("/recensioni", "<priority>0.6</priority>"),
             voce("/contattami", "<priority>0.6</priority>")]
    # Un solo indirizzo per album, sempre la prima pagina: fino al
    # 01/09/2026 qui si elencava anche ogni pagina oltre la prima
    # (?page=2, ?page=3...) di ogni album grande, per far scoprire ai
    # motori di ricerca anche le fotografie oltre la centoventesima. Il
    # problema era vero ma la soluzione sbagliata: Google Search Console
    # segnalava ~2150 URL "scoperte ma non indicizzate" — un solo album
    # da qualche migliaio di foto genera decine di quelle pagine, ognuna
    # con lo stesso titolo/contenuto della pagina 1 e senza un motivo
    # proprio per comparire nei risultati, ed erano proprio queste voci
    # della sitemap a sottometterle attivamente come "pagine ufficiali da
    # indicizzare".
    #
    # Le fotografie oltre pagina 1 restano scopribili lo stesso: le
    # elenca gia' tutte, senza eccezioni, sitemap-immagini.xml (vedi
    # sitemap_immagini() sotto), che le associa alla pagina canonica
    # dell'album invece che a una pagina HTML duplicata a se' stante — il
    # modo corretto secondo le linee guida di Google per la SEO immagini,
    # e che qui esisteva gia' prima di questo cambiamento.
    for r in rows:
        lastmod = (r["updated_at"] or "")[:10]
        mod = f"<lastmod>{lastmod}</lastmod>" if len(lastmod) == 10 else ""
        parts.append(voce(f"/n/{r['slug']}", mod))
    parts.append("</urlset>")
    return Response(content="\n".join(parts), media_type="application/xml")


@router.get("/sitemap-immagini.xml", response_class=Response)
def sitemap_immagini_indice():
    """Indice: elenca le pagine della sitemap delle immagini."""
    settings = get_settings()
    base = settings.site_url.rstrip("/")
    with get_db() as conn:
        n_img = conn.execute(
            "SELECT COUNT(*) c FROM media m JOIN nodes n ON n.id=m.node_id "
            "WHERE n.is_private=0 AND n.hidden=0 AND m.kind='image'").fetchone()["c"]
    pagine = max(1, (n_img + IMG_PER_SITEMAP - 1) // IMG_PER_SITEMAP)
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for i in range(1, pagine + 1):
        parts.append(f"  <sitemap><loc>{base}/sitemap-immagini-{i}.xml</loc></sitemap>")
    parts.append("</sitemapindex>")
    return Response(content="\n".join(parts), media_type="application/xml")


@router.get("/sitemap-immagini-{pagina}.xml", response_class=Response)
def sitemap_immagini(pagina: int):
    """Una pagina della sitemap delle immagini, al massimo 1000 foto."""
    settings = get_settings()
    base = settings.site_url.rstrip("/")
    # Numero di pagina cosi' grande che l'OFFSET calcolato uscirebbe dagli
    # interi di SQLite: quella pagina non esiste (vedi MAX_SQLITE_INT in
    # database.py). Le pagine oltre l'ultima vera continuano a rispondere
    # con una sitemap vuota, come prima: qui si respinge solo cio' che
    # farebbe fallire la query.
    if not 0 < pagina <= MAX_SQLITE_INT // IMG_PER_SITEMAP:
        raise HTTPException(status_code=404, detail="Pagina non trovata")
    offset = max(0, (pagina - 1)) * IMG_PER_SITEMAP
    with get_db() as conn:
        rows = conn.execute(
            "SELECT m.id, m.filename, n.slug, n.title "
            "FROM media m JOIN nodes n ON n.id = m.node_id "
            "WHERE n.is_private=0 AND n.hidden=0 AND m.kind='image' "
            "ORDER BY n.sort_order, m.id LIMIT ? OFFSET ?",
            (IMG_PER_SITEMAP, offset)).fetchall()

    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
             'xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">']
    per_album = {}
    for r in rows:
        per_album.setdefault((r["slug"], r["title"]), []).append(r)
    for (slug, titolo), immagini in per_album.items():
        parts.append(f"  <url><loc>{base}/n/{slug}</loc>")
        for r in immagini:
            didascalia = escape(f"{titolo} — fotografia di Photocarcifo")
            parts.append(f"    <image:image><image:loc>{base}/preview/{r['id']}</image:loc>"
                         f"<image:title>{escape(titolo)}</image:title>"
                         f"<image:caption>{didascalia}</image:caption></image:image>")
        parts.append("  </url>")
    parts.append("</urlset>")
    return Response(content="\n".join(parts), media_type="application/xml")
