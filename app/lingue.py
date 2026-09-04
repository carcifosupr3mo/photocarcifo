"""Traduzione delle pagine pubbliche.

Il sito nasce in italiano, ma gli eventi fotografati sono internazionali:
alle gare svizzere e alle tappe europee arrivano famiglie che l'italiano non
lo leggono. Qui vivono tutti i testi visibili, in cinque lingue.

Come funziona: la lingua scelta viene ricordata in un cookie, non
nell'indirizzo. Ogni pagina ha quindi un solo indirizzo, in italiano, e i
motori di ricerca continuano a vedere esattamente quello che vedevano prima.
Aggiungere /it/, /en/, /fr/... avrebbe moltiplicato per cinque gli indirizzi
del sito e riaperto proprio i problemi di indicizzazione appena chiusi.

Quando manca una traduzione si mostra l'italiano: una frase non tradotta e'
un fastidio, una pagina rotta no.
"""

COOKIE = "pc_lang"
PREDEFINITA = "it"

# Le cinque lingue del pubblico che segue questi eventi: italiano di casa,
# inglese come lingua comune, francese e tedesco per il resto della Svizzera,
# spagnolo per il circuito internazionale.
LINGUE = [
    ("it", "Italiano", "🇮🇹"),
    ("en", "English", "🇬🇧"),
    ("fr", "Français", "🇫🇷"),
    ("de", "Deutsch", "🇩🇪"),
    ("es", "Español", "🇪🇸"),
]

CODICI = [voce[0] for voce in LINGUE]

# Lingue che compaiono nell'indirizzo. L'italiano non c'e': e' la lingua di
# casa e resta senza prefisso, cosi' tutti gli indirizzi gia' in giro
# (collegamenti mandati ai piloti, pagine gia' nell'indice di Google)
# continuano a valere esattamente come prima.
PREFISSI = [c for c in CODICI if c != PREDEFINITA]

# Parti del sito che non hanno una versione tradotta e non devono mai
# prendere il prefisso: file, immagini, pannello, cose per le macchine.
SENZA_PREFISSO = (
    "/static/", "/thumb/", "/thumb2x/", "/preview/", "/cover/", "/social/",
    "/download/", "/zip/", "/video/", "/_originals/", "/admin", "/lingua/",
    # I collegamenti riservati consegnati ai clienti devono restare uno e
    # uno solo: un secondo indirizzo per lo stesso album (o per la stessa
    # foto condivisa) e' un secondo modo di ritrovarselo in giro. La lingua
    # dentro l'album segue il cookie.
    "/p/", "/f/",
    "/healthz", "/robots.txt", "/sitemap", "/novita.xml", "/favicon.ico",
)


def separa_prefisso(percorso: str):
    """Divide "/en/n/bmx" in ("en", "/n/bmx").

    Restituisce (None, percorso) se non c'e' nessun prefisso di lingua.
    """
    for codice in CODICI:                      # anche "it", per poterlo togliere
        if percorso == f"/{codice}":
            return codice, "/"
        if percorso.startswith(f"/{codice}/"):
            return codice, percorso[len(codice) + 1:]
    return None, percorso


def con_prefisso(percorso: str, codice: str) -> str:
    """Lo stesso indirizzo nella lingua indicata.

    In italiano l'indirizzo resta nudo; nelle altre quattro prende davanti
    il codice della lingua.
    """
    percorso = percorso or "/"
    if codice == PREDEFINITA or codice not in CODICI:
        return percorso
    if percorso == "/":
        # Con la barra in fondo: e' la forma che compare anche nel canonical
        # della pagina iniziale. Se le due non combaciassero, Google
        # troverebbe un hreflang che punta a un indirizzo il quale a sua
        # volta ne dichiara un altro come ufficiale, e lascerebbe perdere.
        return f"/{codice}/"
    return f"/{codice}{percorso}"


def traducibile(percorso: str) -> bool:
    """Vero se di questo indirizzo esiste una versione in altre lingue."""
    return not any(percorso.startswith(p) for p in SENZA_PREFISSO)


def normalizza(codice) -> str:
    """Codice di lingua valido, altrimenti l'italiano."""
    if not codice:
        return PREDEFINITA
    c = str(codice).strip().lower()[:2]
    return c if c in CODICI else PREDEFINITA


def lingua_di(request) -> str:
    """Lingua di questa pagina.

    Comanda l'indirizzo: /en/n/bmx e' inglese e basta, chiunque lo apra e
    qualunque cookie abbia. E' la regola che rende possibile ai motori di
    ricerca indicizzare le traduzioni: un indirizzo, una lingua, sempre la
    stessa. Senza, la stessa pagina avrebbe cinque contenuti diversi a
    seconda di chi la chiede, e Google ne indicizzerebbe uno solo.

    Sugli indirizzi senza prefisso (l'italiano) vale poi il cookie, cioe'
    una scelta esplicita, e infine la lingua del browser.
    """
    dal_indirizzo = getattr(getattr(request, "state", None), "pc_lingua", None)
    if dal_indirizzo:
        return dal_indirizzo
    try:
        salvata = request.cookies.get(COOKIE)
    except AttributeError:
        return PREDEFINITA
    if salvata:
        return normalizza(salvata)
    intestazione = ""
    try:
        intestazione = request.headers.get("accept-language", "")
    except AttributeError:
        pass
    for pezzo in intestazione.split(","):
        codice = pezzo.split(";")[0].strip().lower()[:2]
        if codice in CODICI:
            return codice
    return PREDEFINITA


def nome_lingua(codice: str) -> str:
    for c, nome, _ in LINGUE:
        if c == codice:
            return nome
    return LINGUE[0][1]


def bandiera(codice: str) -> str:
    for c, _, segno in LINGUE:
        if c == codice:
            return segno
    return LINGUE[0][2]


# --- I testi ---------------------------------------------------------------
# Chiave simbolica, poi una riga per lingua. L'italiano e' sempre presente:
# e' quello che si vede se una traduzione manca.

TESTI = {
    # Intestazione e piede di pagina
    "nav.aria": {
        "it": "Navigazione principale", "en": "Main navigation",
        "fr": "Navigation principale", "de": "Hauptnavigation",
        "es": "Navegación principal"},
    "nav.salta": {
        "it": "Vai al contenuto", "en": "Skip to content",
        "fr": "Aller au contenu", "de": "Zum Inhalt springen",
        "es": "Ir al contenido"},
    "nav.portfolio": {
        "it": "Portfolio", "en": "Portfolio", "fr": "Portfolio",
        "de": "Portfolio", "es": "Portafolio"},
    "nav.cerca": {
        "it": "Cerca", "en": "Search", "fr": "Rechercher",
        "de": "Suchen", "es": "Buscar"},
    "nav.recensioni": {
        "it": "Recensioni", "en": "Reviews", "fr": "Avis",
        "de": "Bewertungen", "es": "Opiniones"},
    "nav.raduni": {
        "it": "Raduni", "en": "Meet-ups", "fr": "Rassemblements",
        "de": "Treffen", "es": "Quedadas"},
    "nav.contattami": {
        "it": "Contattami", "en": "Contact me", "fr": "Contactez-moi",
        "de": "Kontaktiere mich", "es": "Contáctame"},
    "nav.accedi": {
        "it": "Accedi", "en": "Sign in", "fr": "Connexion",
        "de": "Anmelden", "es": "Acceder"},
    "nav.dashboard": {
        "it": "Dashboard", "en": "Dashboard", "fr": "Tableau de bord",
        "de": "Übersicht", "es": "Panel"},
    "nav.menu": {
        "it": "Menu", "en": "Menu", "fr": "Menu", "de": "Menü",
        "es": "Menú"},
    "nav.lingua": {
        "it": "Lingua", "en": "Language", "fr": "Langue",
        "de": "Sprache", "es": "Idioma"},
    "foot.social": {
        "it": "Contatti e social", "en": "Contact and social",
        "fr": "Contacts et réseaux sociaux",
        "de": "Kontakt und soziale Netzwerke",
        "es": "Contacto y redes sociales"},
    "foot.condizioni": {
        "it": "Condizioni", "en": "Terms", "fr": "Conditions",
        "de": "Bedingungen", "es": "Condiciones"},
    "foot.email": {
        "it": "Email", "en": "Email", "fr": "E-mail",
        "de": "E-Mail", "es": "Correo"},
    "meta.descrizione": {
        "it": "Fotografia dinamica e cinematografica: moto, auto, eventi, sport, ritratti.",
        "en": "Dynamic, cinematic photography: motorbikes, cars, events, sport, portraits.",
        "fr": "Photographie dynamique et cinématographique : motos, voitures, événements, sport, portraits.",
        "de": "Dynamische, filmische Fotografie: Motorräder, Autos, Events, Sport, Porträts.",
        "es": "Fotografía dinámica y cinematográfica: motos, coches, eventos, deporte, retratos."},

    # Pagina iniziale
    "home.descrizione": {
        "it": "Ciao, sono Nathan. Fotografia dinamica, pulita e cinematografica: moto, auto, eventi, sport e ritratti.",
        "en": "Hi, I'm Nathan. Dynamic, clean and cinematic photography: motorbikes, cars, events, sport and portraits.",
        "fr": "Bonjour, je suis Nathan. Photographie dynamique, épurée et cinématographique : motos, voitures, événements, sport et portraits.",
        "de": "Hallo, ich bin Nathan. Dynamische, klare und filmische Fotografie: Motorräder, Autos, Events, Sport und Porträts.",
        "es": "Hola, soy Nathan. Fotografía dinámica, limpia y cinematográfica: motos, coches, eventos, deporte y retratos."},
    "home.eyebrow": {
        "it": "Fotografo — Moto, auto, eventi",
        "en": "Photographer — Motorbikes, cars, events",
        "fr": "Photographe — Motos, voitures, événements",
        "de": "Fotograf — Motorräder, Autos, Events",
        "es": "Fotógrafo — Motos, coches, eventos"},
    "home.saluto": {
        "it": "Ciao, sono Photocarcifo. Scatti motorsport, ma anche ritratti e momenti più tranquilli",
        "en": "Hi, I'm Photocarcifo. Motorsport shots, but also portraits and quieter moments",
        "fr": "Bonjour, je suis Photocarcifo. Photos motorsport, mais aussi portraits et moments plus calmes",
        "de": "Hallo, ich bin Photocarcifo. Motorsport-Fotos, aber auch Porträts und ruhigere Momente",
        "es": "Hola, soy Photocarcifo. Fotos de motorsport, pero también retratos y momentos más tranquilos"},
    "home.lead": {
        "it": "Ho 18 anni e la fotografia è il mio modo di raccontare ciò che mi ispira.",
        "en": "I'm 18, and photography is how I tell the story of what inspires me.",
        "fr": "J'ai 18 ans et la photographie est ma façon de raconter ce qui m'inspire.",
        "de": "Ich bin 18, und die Fotografie ist meine Art zu erzählen, was mich begeistert.",
        "es": "Tengo 18 años y la fotografía es mi manera de contar lo que me inspira."},
    "home.p1": {
        "it": "Tutto è iniziato come una passione, ma con il tempo è diventata una vera attività che porto avanti con impegno e tanta voglia di migliorarmi.",
        "en": "It started as a passion, and over time it has become real work that I pursue with commitment and a constant urge to get better.",
        "fr": "Tout a commencé comme une passion, puis c'est devenu une véritable activité que je mène avec sérieux et une grande envie de progresser.",
        "de": "Angefangen hat alles als Leidenschaft, mit der Zeit ist daraus eine richtige Tätigkeit geworden, die ich mit Einsatz und viel Lust am Besserwerden verfolge.",
        "es": "Todo empezó como una pasión, pero con el tiempo se ha convertido en una actividad real que llevo adelante con dedicación y muchas ganas de mejorar."},
    "home.p2": {
        "it": "Il mio stile è dinamico, pulito e cinematografico. Mi piace creare immagini che abbiano carattere e che facciano rivivere le emozioni di quel momento, non semplicemente scattare una foto.",
        "en": "My style is dynamic, clean and cinematic. I like making images with character, images that bring back the feeling of the moment, rather than just taking a picture.",
        "fr": "Mon style est dynamique, épuré et cinématographique. J'aime créer des images qui ont du caractère et qui font revivre l'émotion de l'instant, pas simplement prendre une photo.",
        "de": "Mein Stil ist dynamisch, klar und filmisch. Ich mache gerne Bilder mit Charakter, die das Gefühl des Moments zurückbringen, statt einfach nur ein Foto zu schiessen.",
        "es": "Mi estilo es dinámico, limpio y cinematográfico. Me gusta crear imágenes con carácter, que hagan revivir la emoción de ese momento, no simplemente hacer una foto."},
    "home.p3": {
        "it": "Lavoro principalmente con moto e auto, ma realizzo anche servizi per eventi, sport, ritratti e contenuti per social media. Ogni shooting è diverso, perché ogni persona e ogni storia meritano qualcosa di unico.",
        "en": "I work mainly with motorbikes and cars, but I also shoot events, sport, portraits and social media content. Every shoot is different, because every person and every story deserves something of their own.",
        "fr": "Je travaille surtout avec des motos et des voitures, mais je réalise aussi des reportages d'événements, de sport, des portraits et des contenus pour les réseaux sociaux. Chaque séance est différente, parce que chaque personne et chaque histoire méritent quelque chose d'unique.",
        "de": "Ich arbeite vor allem mit Motorrädern und Autos, fotografiere aber auch Events, Sport, Porträts und Inhalte für Social Media. Jedes Shooting ist anders, weil jeder Mensch und jede Geschichte etwas Eigenes verdienen.",
        "es": "Trabajo sobre todo con motos y coches, pero también hago reportajes de eventos, deporte, retratos y contenido para redes sociales. Cada sesión es distinta, porque cada persona y cada historia merecen algo único."},
    "home.p4": {
        "it": "Se cerchi il classico fotografo che ti mette in posa e basta, non sono la persona giusta. Se invece vuoi divertirti durante lo shooting e ottenere foto che sembrano uscite da un video cinematografico, allora ci siamo.",
        "en": "If you're after the classic photographer who just puts you in a pose, I'm not your man. If you want to enjoy the shoot and end up with photos that look like stills from a film, then we'll get along.",
        "fr": "Si vous cherchez le photographe classique qui se contente de vous mettre en pose, je ne suis pas la bonne personne. Si en revanche vous voulez vous amuser pendant la séance et obtenir des photos dignes d'un film, alors nous sommes faits pour nous entendre.",
        "de": "Wenn du den klassischen Fotografen suchst, der dich nur in Pose stellt, bin ich der Falsche. Wenn du beim Shooting Spass haben und Fotos bekommen willst, die aussehen wie aus einem Film, dann passt es.",
        "es": "Si buscas al fotógrafo clásico que solo te pone en pose, no soy la persona indicada. Pero si quieres divertirte durante la sesión y conseguir fotos que parezcan salidas de una película, entonces nos entenderemos."},
    "home.chiusura": {
        "it": "Le migliori storie iniziano sempre con un semplice scatto.",
        "en": "The best stories always begin with a single frame.",
        "fr": "Les plus belles histoires commencent toujours par un simple déclic.",
        "de": "Die besten Geschichten beginnen immer mit einer einzigen Aufnahme.",
        "es": "Las mejores historias siempre empiezan con un simple disparo."},
    "home.cta.testo": {
        "it": "Vuoi prenotare uno shooting? Scrivimi:",
        "en": "Want to book a shoot? Get in touch:",
        "fr": "Vous voulez réserver une séance ? Écrivez-moi :",
        "de": "Du möchtest ein Shooting buchen? Schreib mir:",
        "es": "¿Quieres reservar una sesión? Escríbeme:"},
    "home.cta.instagram": {
        "it": "Scrivimi su Instagram", "en": "Message me on Instagram",
        "fr": "Écrivez-moi sur Instagram", "de": "Schreib mir auf Instagram",
        "es": "Escríbeme en Instagram"},
    "home.cta.email": {
        "it": "Scrivimi via email", "en": "Email me",
        "fr": "Écrivez-moi par email", "de": "Schreib mir per E-Mail",
        "es": "Escríbeme por email"},
    "home.vuoto": {
        "it": "Nessun album disponibile.", "en": "No albums available.",
        "fr": "Aucun album disponible.", "de": "Keine Alben verfügbar.",
        "es": "No hay álbumes disponibles."},
    "home.cerca_placeholder": {
        "it": "Cerca album, evento o numero foto…",
        "en": "Search albums, events or photo number…",
        "fr": "Cherchez un album, un événement ou un numéro de photo…",
        "de": "Alben, Events oder Fotonummer suchen…",
        "es": "Busca álbumes, eventos o número de foto…"},

    # Ordinamento
    "ord.eti": {
        "it": "Ordina", "en": "Sort", "fr": "Trier", "de": "Sortieren",
        "es": "Ordenar"},
    "ord.recenti": {
        "it": "Più recenti", "en": "Newest", "fr": "Plus récents",
        "de": "Neueste", "es": "Más recientes"},
    "ord.vecchi": {
        "it": "Più vecchi", "en": "Oldest", "fr": "Plus anciens",
        "de": "Älteste", "es": "Más antiguos"},
    "ord.nome": {
        "it": "Nome", "en": "Name", "fr": "Nom", "de": "Name", "es": "Nombre"},
    "ord.foto": {
        "it": "Più foto", "en": "Most photos", "fr": "Plus de photos",
        "de": "Meiste Fotos", "es": "Más fotos"},

    # Parole ricorrenti
    "com.foto": {
        "it": "foto", "en": "photos", "fr": "photos", "de": "Fotos",
        "es": "fotos"},
    "com.privato": {
        "it": "Privato", "en": "Private", "fr": "Privé", "de": "Privat",
        "es": "Privado"},
    "com.home": {
        "it": "Home", "en": "Home", "fr": "Accueil", "de": "Start",
        "es": "Inicio"},
    "com.percorso": {
        "it": "Percorso", "en": "Breadcrumb", "fr": "Fil d'Ariane",
        "de": "Pfad", "es": "Ruta"},
    "com.pagine": {
        "it": "Pagine", "en": "Pages", "fr": "Pages", "de": "Seiten",
        "es": "Páginas"},
    "com.indietro": {
        "it": "Indietro", "en": "Back", "fr": "Précédent", "de": "Zurück",
        "es": "Atrás"},
    "com.altre": {
        "it": "Altre foto", "en": "More photos", "fr": "Plus de photos",
        "de": "Weitere Fotos", "es": "Más fotos"},
    "com.pagina_di": {
        "it": "Pagina {p} di {n}", "en": "Page {p} of {n}",
        "fr": "Page {p} sur {n}", "de": "Seite {p} von {n}",
        "es": "Página {p} de {n}"},
    "com.torna": {
        "it": "Torna al portfolio", "en": "Back to the portfolio",
        "fr": "Retour au portfolio", "de": "Zurück zum Portfolio",
        "es": "Volver al portafolio"},

    # Pagina di un album
    "node.descrizione": {
        "it": "{n} foto di {titolo}.", "en": "{n} photos of {titolo}.",
        "fr": "{n} photos de {titolo}.", "de": "{n} Fotos von {titolo}.",
        "es": "{n} fotos de {titolo}."},
    "node.vuota": {
        "it": "Questa cartella è vuota.", "en": "This folder is empty.",
        "fr": "Ce dossier est vide.", "de": "Dieser Ordner ist leer.",
        "es": "Esta carpeta está vacía."},
    "node.scarica_tutto": {
        "it": "Scarica tutto", "en": "Download all",
        "fr": "Tout télécharger", "de": "Alle herunterladen",
        "es": "Descargar todo"},
    "node.download_disattivi": {
        "it": "Le fotografie sono disponibili per la visualizzazione. I download non sono ancora attivi.",
        "en": "The photos are available to view. Downloads are not yet enabled.",
        "fr": "Les photos sont disponibles pour la visualisation. Les téléchargements ne sont pas encore activés.",
        "de": "Die Fotos können angesehen werden. Downloads sind noch nicht aktiviert.",
        "es": "Las fotos están disponibles para ver. Las descargas aún no están activadas."},
    "node.seleziona": {
        "it": "Seleziona", "en": "Select", "fr": "Sélectionner",
        "de": "Auswählen", "es": "Seleccionar"},
    "node.seleziona_aiuto": {
        "it": "Seleziona più foto", "en": "Select multiple photos",
        "fr": "Sélectionner plusieurs photos", "de": "Mehrere Fotos auswählen",
        "es": "Seleccionar varias fotos"},
    "node.controlli_aiuto": {
        "it": "❤️ Salva le preferite · ☑ Seleziona più foto",
        "en": "❤️ Save favourites · ☑ Select multiple photos",
        "fr": "❤️ Enregistrer les favoris · ☑ Sélectionner plusieurs photos",
        "de": "❤️ Favoriten speichern · ☑ Mehrere Fotos auswählen",
        "es": "❤️ Guardar favoritas · ☑ Seleccionar varias fotos"},
    "node.scarica_sel": {
        "it": "Scarica selezione", "en": "Download selection",
        "fr": "Télécharger la sélection", "de": "Auswahl herunterladen",
        "es": "Descargar selección"},
    "node.condividi_sel": {
        "it": "Condividi selezione", "en": "Share selection",
        "fr": "Partager la sélection", "de": "Auswahl teilen",
        "es": "Compartir selección"},
    "node.cestino": {
        "it": "Sposta nel cestino", "en": "Move to trash",
        "fr": "Mettre à la corbeille", "de": "In den Papierkorb",
        "es": "Mover a la papelera"},
    "node.scarica_pref": {
        "it": "Scarica preferite", "en": "Download favourites",
        "fr": "Télécharger les favoris", "de": "Favoriten herunterladen",
        "es": "Descargar favoritas"},
    "node.annulla": {
        "it": "Annulla", "en": "Cancel", "fr": "Annuler", "de": "Abbrechen",
        "es": "Cancelar"},
    "node.vista": {
        "it": "Vista", "en": "View", "fr": "Affichage", "de": "Ansicht",
        "es": "Vista"},
    "node.griglia": {
        "it": "Griglia", "en": "Grid", "fr": "Grille", "de": "Raster",
        "es": "Cuadrícula"},
    "node.grande": {
        "it": "Grande", "en": "Large", "fr": "Grand", "de": "Gross",
        "es": "Grande"},
    "node.molte": {
        "it": "Molte foto per riga", "en": "Several photos per row",
        "fr": "Plusieurs photos par ligne", "de": "Mehrere Fotos pro Zeile",
        "es": "Varias fotos por fila"},
    "node.una": {
        "it": "Una foto per riga", "en": "One photo per row",
        "fr": "Une photo par ligne", "de": "Ein Foto pro Zeile",
        "es": "Una foto por fila"},
    "node.da_a": {
        "it": "Foto da {a} a {b} di {tot}", "en": "Photos {a} to {b} of {tot}",
        "fr": "Photos {a} à {b} sur {tot}", "de": "Fotos {a} bis {b} von {tot}",
        "es": "Fotos {a} a {b} de {tot}"},

    # Ricerca
    "src.titolo": {
        "it": "Cerca", "en": "Search", "fr": "Rechercher", "de": "Suchen",
        "es": "Buscar"},
    "src.eyebrow": {
        "it": "Ricerca", "en": "Search", "fr": "Recherche", "de": "Suche",
        "es": "Búsqueda"},
    "src.btn": {
        "it": "Cerca", "en": "Search", "fr": "Rechercher", "de": "Suchen",
        "es": "Buscar"},
    "node.tutte": {
        "it": "Tutte in questa pagina", "en": "All on this page",
        "fr": "Toutes sur cette page", "de": "Alle auf dieser Seite",
        "es": "Todas en esta página"},
    "src.placeholder": {
        "it": "Numero di gara, evento, anno…",
        "en": "Race number, event, year…",
        "fr": "Numéro de course, événement, année…",
        "de": "Startnummer, Event, Jahr…",
        "es": "Dorsal, evento, año…"},
    "src.aiuto": {
        "it": "Cerca quello che ti interessa: il numero della tua tabella, il nome di un evento, una categoria o un anno.",
        "en": "Search for whatever you need: your plate number, the name of an event, a category or a year.",
        "fr": "Cherchez ce que vous voulez : votre numéro de plaque, le nom d'un événement, une catégorie ou une année.",
        "de": "Suche, was du brauchst: deine Startnummer, den Namen eines Events, eine Kategorie oder ein Jahr.",
        "es": "Busca lo que necesites: tu número de placa, el nombre de un evento, una categoría o un año."},
    "src.numero": {
        "it": "Numero {n}", "en": "Number {n}", "fr": "Numéro {n}",
        "de": "Nummer {n}", "es": "Número {n}"},
    "src.trovate": {
        "it": "{tot} fotografie con il numero {n}",
        "en": "{tot} photos showing number {n}",
        "fr": "{tot} photos avec le numéro {n}",
        "de": "{tot} Fotos mit der Nummer {n}",
        "es": "{tot} fotos con el número {n}"},
    "src.trovata": {
        "it": "1 fotografia con il numero {n}",
        "en": "1 photo showing number {n}",
        "fr": "1 photo avec le numéro {n}",
        "de": "1 Foto mit der Nummer {n}",
        "es": "1 foto con el número {n}"},
    "src.pagina": {
        "it": "pagina {p} di {n}", "en": "page {p} of {n}",
        "fr": "page {p} sur {n}", "de": "Seite {p} von {n}",
        "es": "página {p} de {n}"},
    "src.nessuna": {
        "it": "Nessuna fotografia con il numero {n}.",
        "en": "No photos showing number {n}.",
        "fr": "Aucune photo avec le numéro {n}.",
        "de": "Keine Fotos mit der Nummer {n}.",
        "es": "No hay fotos con el número {n}."},
    "src.attesa": {
        "it": "Le foto caricate da poco potrebbero non essere ancora state analizzate. Riprova più tardi, oppure sfoglia le cartelle dalla home.",
        "en": "Photos uploaded recently may not have been analysed yet. Try again later, or browse the folders from the home page.",
        "fr": "Les photos ajoutées récemment n'ont peut-être pas encore été analysées. Réessayez plus tard ou parcourez les dossiers depuis l'accueil.",
        "de": "Kürzlich hochgeladene Fotos sind vielleicht noch nicht ausgewertet. Versuche es später noch einmal oder stöbere von der Startseite aus durch die Ordner.",
        "es": "Puede que las fotos subidas hace poco aún no se hayan analizado. Inténtalo más tarde o explora las carpetas desde el inicio."},
    "src.anche": {
        "it": "Album che contengono «{q}»",
        "en": "Albums matching “{q}”",
        "fr": "Albums contenant « {q} »",
        "de": "Alben mit „{q}“",
        "es": "Álbumes que contienen «{q}»"},
    "src.risultati": {
        "it": "{n} risultati per «{q}»", "en": "{n} results for “{q}”",
        "fr": "{n} résultats pour « {q} »", "de": "{n} Ergebnisse für „{q}“",
        "es": "{n} resultados para «{q}»"},
    "src.nessun_risultato": {
        "it": "Nessun risultato per «{q}».", "en": "No results for “{q}”.",
        "fr": "Aucun résultat pour « {q} ».", "de": "Keine Ergebnisse für „{q}“.",
        "es": "Sin resultados para «{q}»."},
    "src.invito": {
        "it": "Scrivi il numero della tua tabella, il nome di un evento, una categoria o un anno.",
        "en": "Type your plate number, the name of an event, a category or a year.",
        "fr": "Saisissez votre numéro de plaque, le nom d'un événement, une catégorie ou une année.",
        "de": "Gib deine Startnummer, den Namen eines Events, eine Kategorie oder ein Jahr ein.",
        "es": "Escribe tu número de placa, el nombre de un evento, una categoría o un año."},

    # Album protetto da password
    "pwd.titolo": {
        "it": "Cartella protetta", "en": "Protected folder",
        "fr": "Dossier protégé", "de": "Geschützter Ordner",
        "es": "Carpeta protegida"},
    "pwd.eyebrow": {
        "it": "Cartella privata", "en": "Private folder",
        "fr": "Dossier privé", "de": "Privater Ordner",
        "es": "Carpeta privada"},
    "pwd.invito": {
        "it": "Inserisci la password per accedere.",
        "en": "Enter the password to continue.",
        "fr": "Saisissez le mot de passe pour accéder.",
        "de": "Gib das Passwort ein, um fortzufahren.",
        "es": "Introduce la contraseña para acceder."},
    "pwd.campo": {
        "it": "Password", "en": "Password", "fr": "Mot de passe",
        "de": "Passwort", "es": "Contraseña"},
    "pwd.btn": {
        "it": "Accedi", "en": "Continue", "fr": "Accéder", "de": "Weiter",
        "es": "Acceder"},
    "pwd.errore": {
        "it": "Password non corretta.", "en": "Wrong password.",
        "fr": "Mot de passe incorrect.", "de": "Falsches Passwort.",
        "es": "Contraseña incorrecta."},

    # Link scaduto
    "sca.titolo": {
        "it": "Link scaduto", "en": "Link expired", "fr": "Lien expiré",
        "de": "Link abgelaufen", "es": "Enlace caducado"},
    "sca.testo": {
        "it": "Il collegamento a questa galleria non è più attivo. Se ti serve ancora accedere alle fotografie, scrivimi e te ne mando uno nuovo.",
        "en": "The link to this gallery is no longer active. If you still need the photos, get in touch and I'll send you a new one.",
        "fr": "Le lien vers cette galerie n'est plus actif. Si vous avez encore besoin des photos, écrivez-moi et je vous en envoie un nouveau.",
        "de": "Der Link zu dieser Galerie ist nicht mehr aktiv. Wenn du die Fotos noch brauchst, schreib mir und ich schicke dir einen neuen.",
        "es": "El enlace a esta galería ya no está activo. Si todavía necesitas las fotos, escríbeme y te envío uno nuevo."},

    # Condivisione della singola fotografia
    "fcond.titolo": {
        "it": "Una fotografia condivisa", "en": "A shared photograph",
        "fr": "Une photographie partagée", "de": "Ein geteiltes Foto",
        "es": "Una fotografía compartida"},
    "fcond.scarica": {
        "it": "Scarica questa fotografia", "en": "Download this photograph",
        "fr": "Télécharger cette photographie", "de": "Dieses Foto herunterladen",
        "es": "Descargar esta fotografía"},
    "fcond.non_trovata": {
        "it": "Link non valido", "en": "Invalid link",
        "fr": "Lien non valide", "de": "Ungültiger Link",
        "es": "Enlace no válido"},
    "fcond.non_trovata_testo": {
        "it": "Questo collegamento non esiste più, oppure la fotografia non è più raggiungibile. Se ti serve ancora, chiedi un nuovo link.",
        "en": "This link no longer exists, or the photograph is no longer reachable. If you still need it, ask for a new link.",
        "fr": "Ce lien n'existe plus, ou la photographie n'est plus accessible. Si vous en avez encore besoin, demandez un nouveau lien.",
        "de": "Dieser Link existiert nicht mehr, oder das Foto ist nicht mehr erreichbar. Wenn du es noch brauchst, frag nach einem neuen Link.",
        "es": "Este enlace ya no existe, o la fotografía ya no está disponible. Si todavía la necesitas, pide un enlace nuevo."},

    # Condivisione di una selezione di piu' fotografie insieme
    "fcondm.titolo": {
        "it": "Fotografie condivise", "en": "Shared photographs",
        "fr": "Photographies partagées", "de": "Geteilte Fotos",
        "es": "Fotografías compartidas"},
    "fcondm.scarica_tutte": {
        "it": "Scarica tutte (ZIP)", "en": "Download all (ZIP)",
        "fr": "Télécharger tout (ZIP)", "de": "Alle herunterladen (ZIP)",
        "es": "Descargar todo (ZIP)"},

    # Pagine di errore
    "err.codice": {
        "it": "Errore {n}", "en": "Error {n}", "fr": "Erreur {n}",
        "de": "Fehler {n}", "es": "Error {n}"},
    "e404.titolo": {
        "it": "Pagina non trovata", "en": "Page not found",
        "fr": "Page introuvable", "de": "Seite nicht gefunden",
        "es": "Página no encontrada"},
    "e404.testo": {
        "it": "Il link potrebbe essere scaduto oppure l'album non è più pubblico.",
        "en": "The link may have expired, or the album is no longer public.",
        "fr": "Le lien a peut-être expiré, ou l'album n'est plus public.",
        "de": "Der Link ist womöglich abgelaufen, oder das Album ist nicht mehr öffentlich.",
        "es": "Puede que el enlace haya caducado o que el álbum ya no sea público."},
    "e500.titolo": {
        "it": "Qualcosa è andato storto", "en": "Something went wrong",
        "fr": "Une erreur est survenue", "de": "Etwas ist schiefgelaufen",
        "es": "Algo ha ido mal"},
    "e500.testo": {
        "it": "Riprova tra qualche istante.", "en": "Please try again in a moment.",
        "fr": "Réessayez dans un instant.", "de": "Bitte versuche es gleich noch einmal.",
        "es": "Inténtalo de nuevo en un momento."},

    # Preferite
    "pref.titolo": {
        "it": "Le mie preferite", "en": "My favourites", "fr": "Mes favoris",
        "de": "Meine Favoriten", "es": "Mis favoritas"},
    "pref.conteggio": {
        "it": "{n} fotografie scelte", "en": "{n} photos chosen",
        "fr": "{n} photos choisies", "de": "{n} ausgewählte Fotos",
        "es": "{n} fotos elegidas"},
    "pref.conteggio_uno": {
        "it": "1 fotografia scelta", "en": "1 photo chosen",
        "fr": "1 photo choisie", "de": "1 ausgewähltes Foto",
        "es": "1 foto elegida"},
    "pref.in_album": {
        "it": "in {n} album", "en": "across {n} albums",
        "fr": "dans {n} albums", "de": "in {n} Alben",
        "es": "en {n} álbumes"},
    "pref.torna_album": {
        "it": "Torna all'album", "en": "Back to the album",
        "fr": "Retour à l'album", "de": "Zurück zum Album",
        "es": "Volver al álbum"},
    "pref.scarica": {
        "it": "Scarica queste {n}", "en": "Download these {n}",
        "fr": "Télécharger ces {n}", "de": "Diese {n} herunterladen",
        "es": "Descargar estas {n}"},
    "pref.vuoto": {
        "it": "Non hai ancora scelto nessuna fotografia.",
        "en": "You haven't chosen any photos yet.",
        "fr": "Vous n'avez encore choisi aucune photo.",
        "de": "Du hast noch keine Fotos ausgewählt.",
        "es": "Todavía no has elegido ninguna foto."},
    "pref.aiuto": {
        "it": "Apri un album e tocca il cuore sulle foto che ti piacciono: le ritrovi qui.",
        "en": "Open an album and tap the heart on the photos you like: you'll find them here.",
        "fr": "Ouvrez un album et touchez le cœur sur les photos qui vous plaisent : vous les retrouverez ici.",
        "de": "Öffne ein Album und tippe bei den Fotos, die dir gefallen, auf das Herz: hier findest du sie wieder.",
        "es": "Abre un álbum y toca el corazón en las fotos que te gusten: las encontrarás aquí."},
    "pref.vai": {
        "it": "Vai al portfolio", "en": "Go to the portfolio",
        "fr": "Aller au portfolio", "de": "Zum Portfolio",
        "es": "Ir al portafolio"},

    # Calendario raduni
    "rad.titolo": {
        "it": "Calendario raduni", "en": "Meet-up calendar",
        "fr": "Calendrier des rassemblements", "de": "Treffen-Kalender",
        "es": "Calendario de quedadas"},
    "rad.avvertenza": {
        "it": "Avvertenza", "en": "Please note", "fr": "Avertissement",
        "de": "Hinweis", "es": "Aviso"},
    "rad.prossimi": {
        "it": "Prossimi appuntamenti", "en": "Coming up",
        "fr": "Prochains rendez-vous", "de": "Nächste Termine",
        "es": "Próximas citas"},
    "rad.ritrovo": {
        "it": "Ritrovo alle {ora}", "en": "Meeting at {ora}",
        "fr": "Rendez-vous à {ora}", "de": "Treffpunkt um {ora}",
        "es": "Quedada a las {ora}"},
    "rad.mappa": {
        "it": "Apri nelle mappe", "en": "Open in maps",
        "fr": "Ouvrir dans les cartes", "de": "In Karten öffnen",
        "es": "Abrir en mapas"},
    "rad.foto_raduno": {
        "it": "Foto del raduno", "en": "Photos from this meet-up",
        "fr": "Photos du rassemblement", "de": "Fotos vom Treffen",
        "es": "Fotos de la quedada"},
    "rad.vuoto": {
        "it": "Nessun appuntamento in programma al momento.",
        "en": "Nothing scheduled at the moment.",
        "fr": "Aucun rendez-vous prévu pour le moment.",
        "de": "Zurzeit ist nichts geplant.",
        "es": "No hay ninguna cita programada por ahora."},
    "rad.passati": {
        "it": "Già passati", "en": "Past meet-ups", "fr": "Déjà passés",
        "de": "Bereits vorbei", "es": "Ya pasadas"},
    "rad.acc_titolo": {
        "it": "Calendario riservato", "en": "Private calendar",
        "fr": "Calendrier réservé", "de": "Interner Kalender",
        "es": "Calendario reservado"},
    "rad.acc_pagina": {
        "it": "Accesso riservato", "en": "Restricted access",
        "fr": "Accès réservé", "de": "Zugang beschränkt",
        "es": "Acceso restringido"},
    "rad.acc_int": {
        "it": "Questa pagina è accessibile solo a chi conosce la risposta.",
        "en": "This page is only open to those who know the answer.",
        "fr": "Cette page n'est accessible qu'à ceux qui connaissent la réponse.",
        "de": "Diese Seite ist nur zugänglich, wer die Antwort kennt.",
        "es": "Esta página solo es accesible para quien conoce la respuesta."},
    "rad.acc_entra": {
        "it": "Entra", "en": "Enter", "fr": "Entrer", "de": "Eintreten",
        "es": "Entrar"},

    # Recensioni
    "rec.titolo": {
        "it": "Recensioni", "en": "Reviews", "fr": "Avis",
        "de": "Bewertungen", "es": "Opiniones"},
    "rec.sotto": {
        "it": "Hai lavorato con me? Raccontalo qui: mi aiuta, e aiuta chi sta decidendo.",
        "en": "Worked with me? Tell people about it here: it helps me, and it helps whoever is still deciding.",
        "fr": "Vous avez travaillé avec moi ? Racontez-le ici : cela m'aide, et cela aide ceux qui hésitent encore.",
        "de": "Schon mit mir gearbeitet? Erzähl es hier: das hilft mir und allen, die noch überlegen.",
        "es": "¿Has trabajado conmigo? Cuéntalo aquí: me ayuda, y ayuda a quien todavía lo está pensando."},
    "rec.media": {
        "it": "{media} su 5 — {quante} recensioni",
        "en": "{media} out of 5 — {quante} reviews",
        "fr": "{media} sur 5 — {quante} avis",
        "de": "{media} von 5 — {quante} Bewertungen",
        "es": "{media} sobre 5 — {quante} opiniones"},
    "rec.media_una": {
        "it": "{media} su 5 — 1 recensione", "en": "{media} out of 5 — 1 review",
        "fr": "{media} sur 5 — 1 avis", "de": "{media} von 5 — 1 Bewertung",
        "es": "{media} sobre 5 — 1 opinión"},
    "rec.vuoto": {
        "it": "Non c'è ancora nessuna recensione. Puoi essere il primo.",
        "en": "No reviews yet. You could be the first.",
        "fr": "Aucun avis pour le moment. Vous pouvez être le premier.",
        "de": "Noch keine Bewertungen. Du kannst die erste schreiben.",
        "es": "Todavía no hay opiniones. Puedes ser el primero."},
    "rec.scrivi": {
        "it": "Lascia una recensione", "en": "Leave a review",
        "fr": "Laisser un avis", "de": "Bewertung schreiben",
        "es": "Deja una opinión"},
    "rec.nome": {
        "it": "Il tuo nome", "en": "Your name", "fr": "Votre nom",
        "de": "Dein Name", "es": "Tu nombre"},
    "rec.evento": {
        "it": "Gara o servizio (facoltativo)",
        "en": "Race or shoot (optional)",
        "fr": "Course ou séance (facultatif)",
        "de": "Rennen oder Shooting (optional)",
        "es": "Carrera o sesión (opcional)"},
    "rec.evento_ph": {
        "it": "es. Swiss Cup Ginevra 2025", "en": "e.g. Swiss Cup Geneva 2025",
        "fr": "ex. Swiss Cup Genève 2025", "de": "z. B. Swiss Cup Genf 2025",
        "es": "p. ej. Swiss Cup Ginebra 2025"},
    "rec.voto": {
        "it": "Il tuo voto", "en": "Your rating", "fr": "Votre note",
        "de": "Deine Bewertung", "es": "Tu valoración"},
    "rec.stelle": {
        "it": "{n} stelle su 5", "en": "{n} out of 5 stars",
        "fr": "{n} étoiles sur 5", "de": "{n} von 5 Sternen",
        "es": "{n} estrellas de 5"},
    "rec.testo": {
        "it": "Com'è andata", "en": "How did it go", "fr": "Comment ça s'est passé",
        "de": "Wie war es", "es": "Qué tal fue"},
    "rec.testo_ph": {
        "it": "Due righe bastano: cosa ti è piaciuto, come ti sei trovato.",
        "en": "A couple of lines is enough: what you liked, how it felt.",
        "fr": "Deux lignes suffisent : ce qui vous a plu, comment vous vous êtes senti.",
        "de": "Zwei Zeilen reichen: was dir gefallen hat, wie es für dich war.",
        "es": "Con dos líneas basta: qué te gustó, cómo te sentiste."},
    "rec.invia": {
        "it": "Invia", "en": "Send", "fr": "Envoyer", "de": "Senden",
        "es": "Enviar"},
    "rec.moderazione": {
        "it": "La recensione viene pubblicata dopo una lettura, di solito entro un giorno.",
        "en": "Reviews go online after a quick read, usually within a day.",
        "fr": "Les avis sont publiés après relecture, en général sous un jour.",
        "de": "Bewertungen erscheinen nach einer kurzen Durchsicht, meist innerhalb eines Tages.",
        "es": "Las opiniones se publican tras una lectura, normalmente en un día."},
    "rec.grazie": {
        "it": "Grazie! La recensione è arrivata e comparirà qui appena letta.",
        "en": "Thank you! Your review has arrived and will appear here once read.",
        "fr": "Merci ! Votre avis est bien arrivé et paraîtra ici après relecture.",
        "de": "Danke! Deine Bewertung ist angekommen und erscheint hier nach der Durchsicht.",
        "es": "¡Gracias! Tu opinión ha llegado y aparecerá aquí en cuanto se lea."},
    "rec.err_nome": {
        "it": "Scrivi il tuo nome.", "en": "Please enter your name.",
        "fr": "Indiquez votre nom.", "de": "Bitte gib deinen Namen ein.",
        "es": "Escribe tu nombre."},
    "rec.err_voto": {
        "it": "Scegli un voto da 1 a 5 stelle.",
        "en": "Choose a rating from 1 to 5 stars.",
        "fr": "Choisissez une note de 1 à 5 étoiles.",
        "de": "Wähle eine Bewertung von 1 bis 5 Sternen.",
        "es": "Elige una valoración de 1 a 5 estrellas."},
    "rec.err_testo": {
        "it": "Scrivi almeno una frase, così si capisce com'è andata.",
        "en": "Write at least a sentence, so people can tell how it went.",
        "fr": "Écrivez au moins une phrase, pour qu'on comprenne comment ça s'est passé.",
        "de": "Schreib mindestens einen Satz, damit man versteht, wie es war.",
        "es": "Escribe al menos una frase, para que se entienda qué tal fue."},
    "rec.err_troppe": {
        "it": "Hai già scritto le recensioni di oggi. Riprova domani.",
        "en": "You've already sent today's reviews. Please try again tomorrow.",
        "fr": "Vous avez déjà envoyé les avis d'aujourd'hui. Réessayez demain.",
        "de": "Du hast die Bewertungen für heute schon geschrieben. Versuch es morgen wieder.",
        "es": "Ya has enviado las opiniones de hoy. Inténtalo mañana."},

    # Modulo di contatto
    "cont.sottotitolo": {
        "it": "Hai in mente uno shooting o vuoi maggiori informazioni? Inviami una richiesta.",
        "en": "Thinking about a shoot, or just want more information? Send me a request.",
        "fr": "Vous pensez à une séance ou souhaitez plus d'informations ? Envoyez-moi une demande.",
        "de": "Denkst du an ein Shooting oder möchtest du mehr Infos? Schick mir eine Anfrage.",
        "es": "¿Tienes en mente una sesión o quieres más información? Envíame una solicitud."},
    "cont.descrizione": {
        "it": "Scrivimi per uno shooting, un evento o qualsiasi informazione: rispondo il prima possibile.",
        "en": "Write to me for a shoot, an event or any information: I'll reply as soon as possible.",
        "fr": "Écrivez-moi pour une séance, un événement ou toute information : je réponds au plus vite.",
        "de": "Schreib mir für ein Shooting, ein Event oder Infos: ich melde mich so schnell wie möglich.",
        "es": "Escríbeme para una sesión, un evento o cualquier información: respondo lo antes posible."},
    "cont.grazie": {
        "it": "Grazie! Il messaggio è arrivato, ti risponderò appena possibile.",
        "en": "Thank you! Your message has arrived, I'll reply as soon as I can.",
        "fr": "Merci ! Le message est bien arrivé, je vous répondrai dès que possible.",
        "de": "Danke! Die Nachricht ist angekommen, ich melde mich so bald wie möglich.",
        "es": "¡Gracias! El mensaje ha llegado, te responderé en cuanto pueda."},
    "cont.err_nome": {
        "it": "Scrivi nome e cognome.", "en": "Please enter your first and last name.",
        "fr": "Indiquez votre nom et prénom.", "de": "Bitte gib Vor- und Nachnamen ein.",
        "es": "Escribe tu nombre y apellido."},
    "cont.err_email": {
        "it": "Scrivi un indirizzo email valido.",
        "en": "Please enter a valid email address.",
        "fr": "Indiquez une adresse email valide.",
        "de": "Bitte gib eine gültige E-Mail-Adresse ein.",
        "es": "Escribe una dirección de correo válida."},
    "cont.err_motivo": {
        "it": "Scegli il motivo della richiesta.",
        "en": "Please choose the reason for your request.",
        "fr": "Choisissez le motif de la demande.",
        "de": "Bitte wähle den Grund der Anfrage.",
        "es": "Elige el motivo de la solicitud."},
    "cont.err_messaggio": {
        "it": "Scrivi un messaggio.", "en": "Please write a message.",
        "fr": "Écrivez un message.", "de": "Bitte schreib eine Nachricht.",
        "es": "Escribe un mensaje."},
    "cont.err_troppe": {
        "it": "Hai già inviato troppe richieste oggi. Riprova domani.",
        "en": "You've already sent too many requests today. Please try again tomorrow.",
        "fr": "Vous avez déjà envoyé trop de demandes aujourd'hui. Réessayez demain.",
        "de": "Du hast heute schon zu viele Anfragen gesendet. Versuch es morgen wieder.",
        "es": "Ya has enviado demasiadas solicitudes hoy. Inténtalo mañana."},
    "cont.motivo_moto": {
        "it": "Shooting moto", "en": "Motorcycle shoot", "fr": "Séance moto",
        "de": "Motorrad-Shooting", "es": "Sesión de moto"},
    "cont.motivo_auto": {
        "it": "Shooting auto", "en": "Car shoot", "fr": "Séance auto",
        "de": "Auto-Shooting", "es": "Sesión de coche"},
    "cont.motivo_ritratto": {
        "it": "Ritratto", "en": "Portrait", "fr": "Portrait",
        "de": "Porträt", "es": "Retrato"},
    "cont.motivo_evento": {
        "it": "Evento", "en": "Event", "fr": "Événement",
        "de": "Veranstaltung", "es": "Evento"},
    "cont.motivo_sport": {
        "it": "Sport", "en": "Sport", "fr": "Sport",
        "de": "Sport", "es": "Deporte"},
    "cont.motivo_collaborazione": {
        "it": "Collaborazione", "en": "Collaboration", "fr": "Collaboration",
        "de": "Zusammenarbeit", "es": "Colaboración"},
    "cont.motivo_informazioni": {
        "it": "Informazioni", "en": "Information", "fr": "Informations",
        "de": "Informationen", "es": "Información"},
    "cont.motivo_altro": {
        "it": "Altro", "en": "Other", "fr": "Autre",
        "de": "Sonstiges", "es": "Otro"},

    # Condizioni d'uso e privacy
    "priv.titolo": {
        "it": "Condizioni d'uso", "en": "Terms of use",
        "fr": "Conditions d'utilisation", "de": "Nutzungsbedingungen",
        "es": "Condiciones de uso"},
    "priv.breadcrumb": {
        "it": "Condizioni e privacy", "en": "Terms and privacy",
        "fr": "Conditions et confidentialité", "de": "Bedingungen und Datenschutz",
        "es": "Condiciones y privacidad"},
    "priv.pagina": {
        "it": "Condizioni d'uso, copyright e privacy",
        "en": "Terms of use, copyright and privacy",
        "fr": "Conditions d'utilisation, droit d'auteur et confidentialité",
        "de": "Nutzungsbedingungen, Urheberrecht und Datenschutz",
        "es": "Condiciones de uso, derechos de autor y privacidad"},
    "priv.descrizione": {
        "it": "Condizioni d'uso delle fotografie, diritto d'autore e "
              "trattamento dei dati del sito Photocarcifo.",
        "en": "Terms of use for the photographs, copyright and how "
              "Photocarcifo handles personal data.",
        "fr": "Conditions d'utilisation des photographies, droit d'auteur "
              "et traitement des données du site Photocarcifo.",
        "de": "Nutzungsbedingungen der Fotografien, Urheberrecht und "
              "Datenverarbeitung der Website Photocarcifo.",
        "es": "Condiciones de uso de las fotografías, derechos de autor y "
              "tratamiento de datos del sitio Photocarcifo."},
    "priv.aggiornamento": {
        "it": "Ultimo aggiornamento: agosto 2026 — Photocarcifo, Svizzera",
        "en": "Last updated: August 2026 — Photocarcifo, Switzerland",
        "fr": "Dernière mise à jour : août 2026 — Photocarcifo, Suisse",
        "de": "Letzte Aktualisierung: August 2026 — Photocarcifo, Schweiz",
        "es": "Última actualización: agosto de 2026 — Photocarcifo, Suiza"},

    # Pagina "Chi sono".
    #
    # Non ripete i paragrafi della pagina iniziale: due pagine con lo stesso
    # testo sarebbero, per un motore di ricerca, dei doppioni, e proprio i
    # doppioni erano il problema da cui siamo partiti. Qui si racconta il
    # lavoro: che cosa fotografo, come funziona una giornata di gara, che
    # cosa c'e' nell'archivio.
    "bio.pagina": {
        "it": "Chi sono", "en": "About me", "fr": "À propos",
        "de": "Über mich", "es": "Sobre mí"},
    "bio.breadcrumb": {
        "it": "Chi sono", "en": "About", "fr": "À propos",
        "de": "Über mich", "es": "Sobre mí"},
    "bio.eyebrow": {
        "it": "Chi c'è dietro le fotografie",
        "en": "The person behind the photographs",
        "fr": "Qui se cache derrière les photographies",
        "de": "Wer hinter den Fotografien steht",
        "es": "Quién está detrás de las fotografías"},
    "bio.descrizione": {
        "it": "Nathan, fotografo sportivo in Ticino: gare di BMX, motociclismo, hockey, calcio e atletica, con l'archivio completo consultabile per numero di gara.",
        "en": "Nathan, sports photographer in Ticino, Switzerland: BMX, motorcycling, hockey, football and athletics, with the full archive searchable by race number.",
        "fr": "Nathan, photographe sportif au Tessin : BMX, moto, hockey, football et athlétisme, avec les archives complètes consultables par numéro de dossard.",
        "de": "Nathan, Sportfotograf im Tessin: BMX, Motorsport, Hockey, Fussball und Leichtathletik, mit dem vollständigen Archiv, durchsuchbar nach Startnummer.",
        "es": "Nathan, fotógrafo deportivo en el Tesino: BMX, motociclismo, hockey, fútbol y atletismo, con el archivo completo consultable por número de dorsal."},
    "bio.lead": {
        "it": "Fotografo lo sport dove si decide qualcosa: in gara, in pista, in campo.",
        "en": "I photograph sport where something is at stake: in the race, on the track, on the pitch.",
        "fr": "Je photographie le sport là où quelque chose se joue : en course, sur la piste, sur le terrain.",
        "de": "Ich fotografiere Sport dort, wo etwas auf dem Spiel steht: im Rennen, auf der Bahn, auf dem Platz.",
        "es": "Fotografío el deporte donde algo está en juego: en carrera, en la pista, en el campo."},
    "bio.p1": {
        "it": "Seguo soprattutto gare di BMX e di motociclismo, e poi hockey, calcio e atletica. Sono discipline in cui il momento buono dura una frazione di secondo e non torna: si conosce il percorso, si sceglie il punto e si aspetta lì.",
        "en": "I mostly follow BMX and motorcycle races, along with hockey, football and athletics. In these sports the right moment lasts a fraction of a second and never comes back: you learn the course, pick your spot and wait there.",
        "fr": "Je suis surtout des courses de BMX et de moto, ainsi que le hockey, le football et l'athlétisme. Ce sont des disciplines où le bon moment dure une fraction de seconde et ne revient pas : on connaît le parcours, on choisit son poste et on attend.",
        "de": "Ich begleite vor allem BMX- und Motorradrennen, dazu Hockey, Fussball und Leichtathletik. In diesen Sportarten dauert der richtige Moment den Bruchteil einer Sekunde und kommt nicht wieder: Man kennt die Strecke, wählt seinen Platz und wartet dort.",
        "es": "Sigo sobre todo carreras de BMX y de motociclismo, además de hockey, fútbol y atletismo. Son disciplinas en las que el buen momento dura una fracción de segundo y no vuelve: se conoce el recorrido, se elige el punto y se espera allí."},
    "bio.p2": {
        "it": "In una giornata di gara non fotografo solo i primi tre. Riprendo tutti quelli che passano, batteria dopo batteria, perché chi arriva quindicesimo ha fatto la stessa fatica e quasi mai ha una fotografia che lo dimostri.",
        "en": "On a race day I don't just shoot the podium. I photograph everyone who goes past, heat after heat, because whoever finishes fifteenth put in the same effort and almost never has a photograph to show for it.",
        "fr": "Un jour de course, je ne photographie pas seulement le podium. Je prends tous ceux qui passent, manche après manche, parce que celui qui finit quinzième a fourni le même effort et n'a presque jamais de photo pour le prouver.",
        "de": "An einem Renntag fotografiere ich nicht nur das Podest. Ich nehme alle auf, die vorbeikommen, Lauf für Lauf, denn wer Fünfzehnter wird, hat sich genauso angestrengt und hat fast nie ein Bild davon.",
        "es": "En un día de carrera no fotografío solo el podio. Retrato a todos los que pasan, manga tras manga, porque quien acaba decimoquinto ha hecho el mismo esfuerzo y casi nunca tiene una fotografía que lo demuestre."},
    "bio.p3": {
        "it": "Tutto quello che scatto finisce qui, in chiaro e senza registrazione. I numeri di tabella vengono letti automaticamente una a una dalle fotografie: chi ha corso scrive il proprio numero nella ricerca e trova le sue, senza scorrere migliaia di immagini.",
        "en": "Everything I shoot ends up here, in the open and with no sign-up. Race numbers are read automatically from the photographs one by one: riders type their number into the search and find their own, without scrolling through thousands of images.",
        "fr": "Tout ce que je photographie se retrouve ici, en clair et sans inscription. Les numéros de plaque sont lus automatiquement sur les photographies, une par une : il suffit de taper son numéro dans la recherche pour retrouver ses images, sans faire défiler des milliers de photos.",
        "de": "Alles, was ich fotografiere, landet hier, offen und ohne Anmeldung. Die Startnummern werden automatisch Bild für Bild ausgelesen: Wer gefahren ist, gibt seine Nummer in die Suche ein und findet seine Aufnahmen, ohne Tausende von Bildern durchzublättern.",
        "es": "Todo lo que fotografío acaba aquí, a la vista y sin registro. Los números de dorsal se leen automáticamente de las fotografías, una a una: quien ha corrido escribe su número en el buscador y encuentra las suyas, sin recorrer miles de imágenes."},
    "bio.p4": {
        "it": "Oltre alle gare faccio servizi su appuntamento: moto e auto, ritratti, eventi. Lì il lavoro cambia del tutto — si sceglie il posto, la luce e il ritmo — ma l'idea resta la stessa: immagini che facciano rivivere quel momento, non semplici fotografie.",
        "en": "Besides races I also do shoots by appointment: motorbikes and cars, portraits, events. There the work is completely different — you choose the place, the light, the pace — but the idea is the same: images that bring the moment back, not just photographs.",
        "fr": "En dehors des courses, je réalise aussi des séances sur rendez-vous : motos et voitures, portraits, événements. Là, le travail change du tout au tout — on choisit le lieu, la lumière, le rythme — mais l'idée reste la même : des images qui font revivre l'instant, pas de simples photographies.",
        "de": "Neben den Rennen mache ich auch Shootings nach Vereinbarung: Motorräder und Autos, Porträts, Events. Dort ist die Arbeit ganz anders — man wählt Ort, Licht und Rhythmus — aber die Idee bleibt dieselbe: Bilder, die den Moment zurückholen, nicht bloss Fotografien.",
        "es": "Además de las carreras hago sesiones con cita: motos y coches, retratos, eventos. Ahí el trabajo cambia por completo — se elige el lugar, la luz y el ritmo — pero la idea es la misma: imágenes que hagan revivir ese momento, no simples fotografías."},
    "bio.numeri_tit": {
        "it": "L'archivio in numeri", "en": "The archive in numbers",
        "fr": "Les archives en chiffres", "de": "Das Archiv in Zahlen",
        "es": "El archivo en cifras"},
    "bio.n_foto": {
        "it": "fotografie pubblicate", "en": "photographs published",
        "fr": "photographies publiées", "de": "veröffentlichte Fotografien",
        "es": "fotografías publicadas"},
    "bio.n_gallerie": {
        "it": "gallerie", "en": "galleries", "fr": "galeries",
        "de": "Galerien", "es": "galerías"},
    "bio.n_discipline": {
        "it": "discipline", "en": "sports", "fr": "disciplines",
        "de": "Sportarten", "es": "disciplinas"},
    "bio.n_dal": {
        "it": "dal", "en": "since", "fr": "depuis", "de": "seit",
        "es": "desde"},
    "bio.dicono_tit": {
        "it": "Quello che dicono gli altri",
        "en": "What other people say",
        "fr": "Ce que disent les autres",
        "de": "Was andere sagen",
        "es": "Lo que dicen los demás"},
    "bio.dicono_txt": {
        "it": "Le recensioni le scrivono le persone che ho fotografato, e si leggono tutte.",
        "en": "The reviews are written by the people I have photographed, and they are all there to read.",
        "fr": "Les avis sont écrits par les personnes que j'ai photographiées, et ils sont tous consultables.",
        "de": "Die Bewertungen stammen von den Menschen, die ich fotografiert habe, und sie sind alle nachzulesen.",
        "es": "Las opiniones las escriben las personas a las que he fotografiado, y se pueden leer todas."},
    "bio.vai_gallerie": {
        "it": "Guarda le gallerie", "en": "See the galleries",
        "fr": "Voir les galeries", "de": "Zu den Galerien",
        "es": "Ver las galerías"},
    "nav.chi_sono": {
        "it": "Chi sono", "en": "About", "fr": "À propos",
        "de": "Über mich", "es": "Sobre mí"},

    # Pagine di errore.
    #
    # Prima esistevano solo il 404 e il 500: tutto il resto (indirizzo
    # scritto male, accesso negato, troppe richieste) usciva come blocco di
    # dati grezzi, con dentro il nome del parametro e il tipo atteso. A un
    # visitatore non dice niente e a chi cerca punti deboli dice troppo.
    "err.400_tit": {
        "it": "Indirizzo non valido", "en": "Invalid address",
        "fr": "Adresse non valide", "de": "Ungültige Adresse",
        "es": "Dirección no válida"},
    "err.400_txt": {
        "it": "L'indirizzo contiene qualcosa che non si può leggere. Può succedere con un collegamento vecchio o troncato a metà.",
        "en": "The address contains something that cannot be read. This can happen with an old link, or one that got cut in half.",
        "fr": "L'adresse contient quelque chose d'illisible. Cela arrive avec un lien ancien ou coupé en deux.",
        "de": "Die Adresse enthält etwas Unlesbares. Das passiert bei alten oder halb abgeschnittenen Links.",
        "es": "La dirección contiene algo que no se puede leer. Puede pasar con un enlace antiguo o cortado por la mitad."},
    "err.403_tit": {
        "it": "Accesso non consentito", "en": "Access not allowed",
        "fr": "Accès non autorisé", "de": "Kein Zugriff",
        "es": "Acceso no permitido"},
    "err.403_txt": {
        "it": "Questa parte del sito è riservata. Se hai ricevuto un collegamento privato, riaprilo: potrebbe essere scaduto.",
        "en": "This part of the site is private. If you were given a private link, open it again: it may have expired.",
        "fr": "Cette partie du site est réservée. Si vous avez reçu un lien privé, rouvrez-le : il a peut-être expiré.",
        "de": "Dieser Teil der Website ist geschützt. Wenn du einen privaten Link erhalten hast, öffne ihn erneut: er könnte abgelaufen sein.",
        "es": "Esta parte del sitio es privada. Si recibiste un enlace privado, ábrelo de nuevo: puede haber caducado."},
    "err.429_tit": {
        "it": "Troppe richieste", "en": "Too many requests",
        "fr": "Trop de requêtes", "de": "Zu viele Anfragen",
        "es": "Demasiadas peticiones"},
    "err.429_txt": {
        "it": "Sono arrivate troppe richieste in poco tempo. Aspetta un minuto e riprova.",
        "en": "Too many requests arrived in a short time. Wait a minute and try again.",
        "fr": "Trop de requêtes en peu de temps. Attendez une minute et réessayez.",
        "de": "Zu viele Anfragen in kurzer Zeit. Warte eine Minute und versuche es erneut.",
        "es": "Han llegado demasiadas peticiones en poco tiempo. Espera un minuto y vuelve a intentarlo."},
    "err.gen_tit": {
        "it": "Qualcosa non ha funzionato", "en": "Something went wrong",
        "fr": "Quelque chose n'a pas fonctionné", "de": "Etwas hat nicht geklappt",
        "es": "Algo no ha funcionado"},
    "err.gen_txt": {
        "it": "La richiesta non è andata a buon fine. Se il problema si ripete, riprova più tardi.",
        "en": "The request did not go through. If it keeps happening, try again later.",
        "fr": "La requête n'a pas abouti. Si cela se répète, réessayez plus tard.",
        "de": "Die Anfrage ist nicht durchgegangen. Wenn es weiter passiert, versuche es später erneut.",
        "es": "La petición no se ha completado. Si se repite, inténtalo más tarde."},

    # Ultime gallerie e feed
    "nav.novita": {
        "it": "Novità", "en": "What's new", "fr": "Nouveautés",
        "de": "Neu", "es": "Novedades"},
    "nov.titolo": {
        "it": "Ultime gallerie", "en": "Latest galleries",
        "fr": "Dernières galeries", "de": "Neueste Galerien",
        "es": "Últimas galerías"},
    "nov.descrizione": {
        "it": "Le gallerie pubblicate più di recente su Photocarcifo, dalla più nuova alla più vecchia.",
        "en": "The most recently published galleries on Photocarcifo, newest first.",
        "fr": "Les galeries publiées le plus récemment sur Photocarcifo, de la plus récente à la plus ancienne.",
        "de": "Die zuletzt veröffentlichten Galerien auf Photocarcifo, die neueste zuerst.",
        "es": "Las galerías publicadas más recientemente en Photocarcifo, de la más nueva a la más antigua."},
    "nov.sotto": {
        "it": "In ordine di data della gara, non di quando le ho caricate.",
        "en": "Ordered by the date of the event, not by when I uploaded them.",
        "fr": "Classées par date de l'épreuve, et non par date de mise en ligne.",
        "de": "Nach dem Datum des Anlasses geordnet, nicht nach dem Hochladen.",
        "es": "Ordenadas por la fecha de la prueba, no por cuándo las he subido."},
    "nov.feed": {
        "it": "Avvisami delle nuove (feed RSS)",
        "en": "Notify me of new ones (RSS feed)",
        "fr": "M'avertir des nouveautés (flux RSS)",
        "de": "Über Neues informieren (RSS-Feed)",
        "es": "Avisarme de las nuevas (canal RSS)"},
    "nov.foto": {
        "it": "{n} fotografie", "en": "{n} photographs",
        "fr": "{n} photographies", "de": "{n} Fotografien",
        "es": "{n} fotografías"},
}


# --- Testi usati dal JavaScript -------------------------------------------
# Selezione, visualizzatore a schermo intero, preferite, avviso iniziale:
# sono scritte create dal browser dopo il caricamento, quindi non passano
# dai modelli. Vengono consegnate alla pagina come elenco e lette da T().

TESTI.update({
    "js.pref_segna": {
        "it": "Aggiungi ai preferiti", "en": "Add to favourites",
        "fr": "Ajouter aux favoris", "de": "Zu Favoriten hinzufügen",
        "es": "Añadir a favoritas"},
    "js.pref_scarica": {
        "it": "Scarica preferite ({n})", "en": "Download favourites ({n})",
        "fr": "Télécharger les favoris ({n})",
        "de": "Favoriten herunterladen ({n})",
        "es": "Descargar favoritas ({n})"},
    "js.sel_scarica": {
        "it": "Scarica selezione ({n})", "en": "Download selection ({n})",
        "fr": "Télécharger la sélection ({n})",
        "de": "Auswahl herunterladen ({n})",
        "es": "Descargar selección ({n})"},
    "js.sel_condividi": {
        "it": "Condividi selezione ({n})", "en": "Share selection ({n})",
        "fr": "Partager la sélection ({n})", "de": "Auswahl teilen ({n})",
        "es": "Compartir selección ({n})"},
    "js.sel_rimuovi_n": {
        "it": "Rimuovi ({n})", "en": "Remove ({n})", "fr": "Supprimer ({n})",
        "de": "Entfernen ({n})", "es": "Eliminar ({n})"},
    "js.sel_rimuovi": {
        "it": "Rimuovi", "en": "Remove", "fr": "Supprimer", "de": "Entfernen",
        "es": "Eliminar"},
    "js.sel_eco": {
        "it": "{n} selezionate in tutto l'album",
        "en": "{n} selected across the album",
        "fr": "{n} sélectionnées dans tout l'album",
        "de": "{n} im ganzen Album ausgewählt",
        "es": "{n} seleccionadas en todo el álbum"},
    "js.sel_questa": {
        "it": "Seleziona questa foto", "en": "Select this photo",
        "fr": "Sélectionner cette photo", "de": "Dieses Foto auswählen",
        "es": "Seleccionar esta foto"},
    "js.sessione": {
        "it": "Sessione non valida: rientra dal pannello.",
        "en": "Invalid session: sign in again from the panel.",
        "fr": "Session invalide : reconnectez-vous depuis le panneau.",
        "de": "Ungültige Sitzung: melde dich im Panel neu an.",
        "es": "Sesión no válida: vuelve a entrar desde el panel."},
    "js.cestino_una": {
        "it": "Spostare questa foto nel cestino?",
        "en": "Move this photo to the trash?",
        "fr": "Mettre cette photo à la corbeille ?",
        "de": "Dieses Foto in den Papierkorb verschieben?",
        "es": "¿Mover esta foto a la papelera?"},
    "js.cestino_n": {
        "it": "Spostare {n} foto nel cestino?",
        "en": "Move {n} photos to the trash?",
        "fr": "Mettre {n} photos à la corbeille ?",
        "de": "{n} Fotos in den Papierkorb verschieben?",
        "es": "¿Mover {n} fotos a la papelera?"},
    "js.cestino_nota": {
        "it": "I file restano sul NAS e si possono rimettere a posto dal pannello Cestino.",
        "en": "The files stay on the NAS and can be restored from the Trash panel.",
        "fr": "Les fichiers restent sur le NAS et peuvent être restaurés depuis la corbeille.",
        "de": "Die Dateien bleiben auf dem NAS und lassen sich im Papierkorb wiederherstellen.",
        "es": "Los archivos permanecen en el NAS y se pueden restaurar desde la papelera."},
    "js.rimozione": {
        "it": "Rimozione…", "en": "Removing…", "fr": "Suppression…",
        "de": "Wird entfernt…", "es": "Eliminando…"},
    "js.rimozione_ko": {
        "it": "Rimozione non riuscita.", "en": "Removal failed.",
        "fr": "La suppression a échoué.", "de": "Entfernen fehlgeschlagen.",
        "es": "No se ha podido eliminar."},
    # Messaggi degli avvisi. Prima, quando una richiesta non andava a buon
    # fine, il pulsante tornava semplicemente com'era: nessuna spiegazione,
    # e chi guardava premeva di nuovo credendo di aver sbagliato mira.
    "js.rete_ko": {
        "it": "Non è stato possibile completare l'operazione. Controlla la connessione e riprova.",
        "en": "The action could not be completed. Check your connection and try again.",
        "fr": "L'opération n'a pas pu aboutir. Vérifiez votre connexion et réessayez.",
        "de": "Die Aktion konnte nicht abgeschlossen werden. Prüfe die Verbindung und versuche es erneut.",
        "es": "No se ha podido completar la operación. Comprueba la conexión e inténtalo de nuevo."},
    "js.avviso_chiudi": {
        "it": "Chiudi l'avviso", "en": "Dismiss", "fr": "Fermer l'avis",
        "de": "Hinweis schliessen", "es": "Cerrar el aviso"},
    "js.di": {
        "it": "{a} di {b}", "en": "{a} of {b}", "fr": "{a} sur {b}",
        "de": "{a} von {b}", "es": "{a} de {b}"},
    "js.visualizzatore": {
        "it": "Visualizzatore fotografie", "en": "Photo viewer",
        "fr": "Visionneuse de photos", "de": "Fotoansicht",
        "es": "Visor de fotos"},
    "js.chiudi": {
        "it": "Chiudi", "en": "Close", "fr": "Fermer", "de": "Schliessen",
        "es": "Cerrar"},
    "js.precedente": {
        "it": "Foto precedente", "en": "Previous photo",
        "fr": "Photo précédente", "de": "Vorheriges Foto",
        "es": "Foto anterior"},
    "js.successiva": {
        "it": "Foto successiva", "en": "Next photo", "fr": "Photo suivante",
        "de": "Nächstes Foto", "es": "Foto siguiente"},
    "js.scarica_orig": {
        "it": "Scarica originale", "en": "Download original",
        "fr": "Télécharger l'original", "de": "Original herunterladen",
        "es": "Descargar original"},
    "js.condividi_foto": {
        "it": "Condividi questa foto", "en": "Share this photo",
        "fr": "Partager cette photo", "de": "Dieses Foto teilen",
        "es": "Compartir esta foto"},
    "js.condividi_fatto": {
        "it": "Link copiato", "en": "Link copied",
        "fr": "Lien copié", "de": "Link kopiert",
        "es": "Enlace copiado"},
    "js.condividi_ko": {
        "it": "Non riesco a creare il link.", "en": "Can't create the link.",
        "fr": "Impossible de créer le lien.", "de": "Der Link kann nicht erstellt werden.",
        "es": "No puedo crear el enlace."},
    "js.condividi_link": {
        "it": "Link di condivisione", "en": "Sharing link",
        "fr": "Lien de partage", "de": "Freigabelink",
        "es": "Enlace para compartir"},
    "js.condividi_titolo": {
        "it": "Condividi", "en": "Share",
        "fr": "Partager", "de": "Teilen",
        "es": "Compartir"},
    "js.condividi_copia": {
        "it": "Copia link", "en": "Copy link",
        "fr": "Copier le lien", "de": "Link kopieren",
        "es": "Copiar enlace"},
    "js.condividi_whatsapp": {
        "it": "WhatsApp", "en": "WhatsApp",
        "fr": "WhatsApp", "de": "WhatsApp",
        "es": "WhatsApp"},
    "js.condividi_telegram": {
        "it": "Telegram", "en": "Telegram",
        "fr": "Telegram", "de": "Telegram",
        "es": "Telegram"},
    "js.condividi_email": {
        "it": "Email", "en": "Email",
        "fr": "E-mail", "de": "E-Mail",
        "es": "Correo"},
    "js.zip_preparo": {
        "it": "Preparazione dell'archivio in corso…",
        "en": "Preparing the archive…",
        "fr": "Preparation de l'archive…",
        "de": "Archiv wird vorbereitet…",
        "es": "Preparando el archivo…"},
    "js.zip_pronto": {
        "it": "Scaricamento avviato.", "en": "Download started.",
        "fr": "Telechargement lance.", "de": "Download gestartet.",
        "es": "Descarga iniciada."},
    "js.zip_in_corso": {
        "it": "Questo archivio e' gia' in preparazione: aspetta che finisca.",
        "en": "This archive is already being prepared: wait for it to finish.",
        "fr": "Cette archive est deja en preparation : attendez qu'elle se termine.",
        "de": "Dieses Archiv wird bereits vorbereitet: bitte warten.",
        "es": "Este archivo ya se esta preparando: espera a que termine."},
    "js.copertina_metti": {
        "it": "Metti in copertina", "en": "Set as cover",
        "fr": "Definir comme couverture", "de": "Als Titelbild setzen",
        "es": "Poner de portada"},
    "js.copertina_fatta": {
        "it": "Copertina aggiornata", "en": "Cover updated",
        "fr": "Couverture mise a jour", "de": "Titelbild aktualisiert",
        "es": "Portada actualizada"},
    "js.copertina_ko": {
        "it": "Non e' stato possibile cambiare la copertina.",
        "en": "The cover could not be changed.",
        "fr": "Impossible de changer la couverture.",
        "de": "Das Titelbild konnte nicht geandert werden.",
        "es": "No se ha podido cambiar la portada."},
    "js.condividi_altro": {
        "it": "Condividi…", "en": "Share…",
        "fr": "Partager…", "de": "Teilen…",
        "es": "Compartir…"},
    "js.condividi_chiudi": {
        "it": "Chiudi pannello di condivisione", "en": "Close sharing panel",
        "fr": "Fermer le panneau de partage", "de": "Freigabebereich schliessen",
        "es": "Cerrar el panel para compartir"},
    "js.condividi_conta": {
        "it": "{n} fotografie condivise", "en": "{n} photos shared",
        "fr": "{n} photos partagées", "de": "{n} Fotos geteilt",
        "es": "{n} fotos compartidas"},
    "js.condividi_anteprima": {
        "it": "Anteprima della foto", "en": "Photo preview",
        "fr": "Aperçu de la photo", "de": "Fotovorschau",
        "es": "Vista previa de la foto"},
    "js.cookie_aria": {
        "it": "Condizioni d'uso", "en": "Terms of use",
        "fr": "Conditions d'utilisation", "de": "Nutzungsbedingungen",
        "es": "Condiciones de uso"},
    "js.cookie_forte": {
        "it": "Fotografie protette da copyright.",
        "en": "Photographs protected by copyright.",
        "fr": "Photographies protégées par le droit d'auteur.",
        "de": "Fotografien urheberrechtlich geschützt.",
        "es": "Fotografías protegidas por derechos de autor."},
    "js.cookie_testo": {
        "it": "Le immagini di questo sito sono opera di Photocarcifo: puoi usarle per uso personale citando @photocarcifo. Ogni utilizzo commerciale o senza credito richiede autorizzazione. Il sito usa solo cookie tecnici, senza pubblicità né tracciamento.",
        "en": "The images on this site are the work of Photocarcifo: you may use them personally by crediting @photocarcifo. Any commercial use, or use without credit, needs permission. The site uses technical cookies only, with no advertising or tracking.",
        "fr": "Les images de ce site sont l'œuvre de Photocarcifo : vous pouvez les utiliser à titre personnel en créditant @photocarcifo. Tout usage commercial ou sans crédit nécessite une autorisation. Le site n'utilise que des cookies techniques, sans publicité ni suivi.",
        "de": "Die Bilder auf dieser Website stammen von Photocarcifo: für den persönlichen Gebrauch darfst du sie mit Nennung von @photocarcifo verwenden. Jede kommerzielle Nutzung oder Nutzung ohne Namensnennung braucht eine Erlaubnis. Die Website verwendet nur technische Cookies, ohne Werbung und ohne Tracking.",
        "es": "Las imágenes de este sitio son obra de Photocarcifo: puedes usarlas de forma personal citando a @photocarcifo. Cualquier uso comercial o sin crédito requiere autorización. El sitio usa solo cookies técnicas, sin publicidad ni seguimiento."},
    "js.cookie_leggi": {
        "it": "Leggi l'informativa sulla privacy", "en": "Read our Privacy Policy",
        "fr": "Lire notre politique de confidentialité",
        "de": "Datenschutzerklärung lesen",
        "es": "Leer nuestra política de privacidad"},
    "js.cookie_ok": {
        "it": "Accetto", "en": "I agree", "fr": "J'accepte",
        "de": "Einverstanden", "es": "Acepto"},
    "js.nome_titolo": {
        "it": "Prima di scegliere", "en": "Before you choose",
        "fr": "Avant de choisir", "de": "Bevor du auswählst",
        "es": "Antes de elegir"},
    "js.nome_sotto": {
        "it": "Dimmi chi sei, così so a chi appartengono le foto selezionate.",
        "en": "Tell me who you are, so I know whose selection this is.",
        "fr": "Dites-moi qui vous êtes, pour que je sache à qui appartient la sélection.",
        "de": "Sag mir, wer du bist, damit ich weiss, wem die Auswahl gehört.",
        "es": "Dime quién eres, así sé de quién es la selección."},
    "js.nome_cognome": {
        "it": "Nome e cognome", "en": "First and last name",
        "fr": "Nom et prénom", "de": "Vor- und Nachname",
        "es": "Nombre y apellidos"},
    "js.nome_ph_ig": {
        "it": "iltuonome", "en": "yourname", "fr": "votrenom",
        "de": "deinname", "es": "tunombre"},
    "js.nome_ph_nome": {
        "it": "Mario Rossi", "en": "John Smith", "fr": "Jean Dupont",
        "de": "Max Muster", "es": "Juan Pérez"},
    "js.nome_continua": {
        "it": "Continua", "en": "Continue", "fr": "Continuer",
        "de": "Weiter", "es": "Continuar"},
    "js.nome_err_ig": {
        "it": "Scrivi il tuo profilo, oppure passa a «Nome e cognome».",
        "en": "Enter your profile, or switch to “First and last name”.",
        "fr": "Saisissez votre profil, ou passez à « Nom et prénom ».",
        "de": "Gib dein Profil ein oder wechsle zu „Vor- und Nachname“.",
        "es": "Escribe tu perfil o cambia a «Nombre y apellidos»."},
    "js.nome_err_ig2": {
        "it": "Un profilo Instagram contiene solo lettere, numeri, punto e trattino basso.",
        "en": "An Instagram handle only contains letters, numbers, dots and underscores.",
        "fr": "Un profil Instagram ne contient que des lettres, des chiffres, des points et des tirets bas.",
        "de": "Ein Instagram-Profil enthält nur Buchstaben, Zahlen, Punkte und Unterstriche.",
        "es": "Un perfil de Instagram solo contiene letras, números, puntos y guiones bajos."},
    "js.nome_err_nome": {
        "it": "Scrivi nome e cognome, solo lettere.",
        "en": "Enter your first and last name, letters only.",
        "fr": "Saisissez nom et prénom, lettres uniquement.",
        "de": "Gib Vor- und Nachnamen ein, nur Buchstaben.",
        "es": "Escribe nombre y apellidos, solo letras."},
    "js.nome_attimo": {
        "it": "Un attimo…", "en": "One moment…", "fr": "Un instant…",
        "de": "Einen Moment…", "es": "Un momento…"},
    "js.nome_ko": {
        "it": "Non riesco a salvare, riprova.", "en": "Couldn't save, please try again.",
        "fr": "Impossible d'enregistrer, réessayez.",
        "de": "Speichern nicht möglich, versuche es erneut.",
        "es": "No se ha podido guardar, inténtalo de nuevo."},
})


def per_javascript(lingua: str) -> dict:
    """Le sole voci che servono al browser, gia' nella lingua giusta."""
    return {chiave[3:]: traduci(chiave, lingua)
            for chiave in TESTI if chiave.startswith("js.")}


def traduci(chiave: str, lingua: str = PREDEFINITA) -> str:
    voce = TESTI.get(chiave)
    if not voce:
        # Chiave sconosciuta: si mostra la chiave stessa invece di uno
        # spazio vuoto, cosi' l'errore salta all'occhio subito.
        return chiave
    return voce.get(lingua) or voce.get(PREDEFINITA, chiave)
