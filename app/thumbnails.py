"""Generazione e cache delle miniature per foto e video.

Tre misure: 'small' per la griglia, 'card' per gli schermi ad alta densita'
(il doppio di small) e 'medium' per l'anteprima a schermo intero. Dopo il
ridimensionamento viene applicata una leggera maschera di contrasto, che
restituisce alle immagini rimpicciolite la nitidezza persa.
"""
import hashlib
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps, ImageDraw, ImageFilter

from .config import get_settings

SIZE_SMALL = "small"
SIZE_CARD = "card"
SIZE_MEDIUM = "medium"
SIZE_COVER = "cover"
# Immagine che si vede quando un collegamento viene incollato in una chat.
SIZE_SOCIAL = "social"

# Misura fissa dell'anteprima social: 1200x630 e' il formato che WhatsApp,
# Telegram, Facebook e Instagram si aspettano. Fuori da queste proporzioni
# ritagliano loro, spesso male. L'immagine viene ritagliata al centro.
SOCIAL_L, SOCIAL_H = 1200, 630


def _target_long_edge(size: str) -> int:
    settings = get_settings()
    piccolo = max(getattr(settings, "thumb_small", 400) or 400, 640)
    if size == SIZE_SOCIAL:
        return SOCIAL_L
    if size == SIZE_MEDIUM:
        return max(getattr(settings, "thumb_medium", 1200) or 1200, 1800)
    if size == SIZE_CARD:
        return piccolo * 2
    return piccolo


FORMATO_JPEG = "jpeg"
FORMATO_WEBP = "webp"
FORMATO_AVIF = "avif"


def _quality(size: str, formato: str = FORMATO_JPEG) -> int:
    """Qualita' di compressione, per misura e per formato.

    Le due scale non coincidono: sul WebP lo stesso numero produce file piu'
    pesanti a parita' di resa visiva. Misurato sulle fotografie di questo
    sito, WebP 82 e' indistinguibile da JPEG 88 e pesa il 40% in meno,
    mentre usare 88 anche sul WebP annullerebbe quasi tutto il guadagno.
    """
    settings = get_settings()
    base = getattr(settings, "thumb_quality", 82) or 82
    if size == SIZE_COVER:
        jpeg = 76
    elif size == SIZE_SOCIAL:
        # WhatsApp scarta le anteprime che superano i 300 KB: meglio un
        # filo di compressione in piu' che nessuna immagine del tutto.
        jpeg = 72
    else:
        jpeg = max(base, 90 if size == SIZE_MEDIUM else 88)
    if formato == FORMATO_WEBP:
        return max(70, jpeg - 6)
    if formato == FORMATO_AVIF:
        # La scala dell'AVIF non e' quella degli altri due: lo stesso numero
        # significa una cosa diversa. Questi valori sono stati scelti
        # guardando le fotografie ingrandite tre volte sul numero di gara,
        # non a occhio sui numeri: sotto 55 l'AVIF comincia a lisciare la
        # grana dell'asfalto e della ghiaia, che e' proprio cio' che
        # distingue una foto di gara da un fondale finto. A 55-58 la grana
        # resta e il file pesa comunque un terzo meno del WebP.
        return 58 if size == SIZE_MEDIUM else 55
    return jpeg

# Estensione e tipo MIME di ciascun formato
_ESTENSIONE = {FORMATO_JPEG: "jpg", FORMATO_WEBP: "webp", FORMATO_AVIF: "avif"}
TIPO_MIME = {FORMATO_JPEG: "image/jpeg", FORMATO_WEBP: "image/webp",
             FORMATO_AVIF: "image/avif"}


def _cache_key(rel_path: str, mtime: float, size: str,
               formato: str = FORMATO_JPEG) -> str:
    """Chiave della miniatura in cache.

    Per il JPEG la chiave resta identica a prima, cosi' le miniature gia'
    generate continuano a valere. Il WebP ha una chiave propria: sono due
    file distinti, si serve l'uno o l'altro a seconda del browser.
    """
    raw = f"v2|{rel_path}|{mtime}|{size}"
    if formato != FORMATO_JPEG:
        raw += f"|{formato}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_file(key: str, formato: str = FORMATO_JPEG) -> Path:
    settings = get_settings()
    folder = settings.thumb_cache_path / key[:2]
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{key}.{_ESTENSIONE.get(formato, 'jpg')}"


# --- Firma di proprieta' incorporata nelle copie -------------------------
#
# Il ridimensionamento butta via tutti i dati della fotografia originale:
# le copie che il sito manda in giro (miniature, anteprime, immagini delle
# chat) uscivano quindi senza autore ne' diritti. Una fotografia salvata da
# qualcuno diventa cosi' un file anonimo, e chi la ritrova non ha modo di
# sapere di chi sia.
#
# Si scrivono due cose, perche' due mondi diversi le leggono:
#   - EXIF Artist/Copyright: quello che vedono Windows, macOS e i programmi
#     di fotografia quando si guardano le proprieta' del file;
#   - XMP (lo standard IPTC): quello che leggono Google Immagini e le
#     agenzie. E' anche cio' che permette a Google di mostrare accanto alla
#     fotografia il collegamento a chi ne detiene i diritti.
#
# L'anno non e' quello di oggi ma quello dello scatto, letto dalla
# fotografia stessa: scrivere "© 2026" su una gara del 2023 sarebbe falso.
_TAG_ARTISTA = 0x013B
_TAG_DIRITTI = 0x8298
_TAG_DATA_SCATTO = 0x9003
_TAG_DATA = 0x0132


def _anno_scatto(im: Image.Image) -> str:
    from datetime import datetime
    try:
        ex = im.getexif()
        for tag in (_TAG_DATA_SCATTO, _TAG_DATA):
            valore = str(ex.get(tag) or "")
            if len(valore) >= 4 and valore[:4].isdigit():
                return valore[:4]
    except Exception:
        pass
    return str(datetime.now().year)


def _diritti(im: Image.Image):
    """Coppia (exif, xmp) da incorporare nella copia."""
    settings = get_settings()
    nome = getattr(settings, "site_name", "Photocarcifo")
    sito = str(getattr(settings, "site_url", "")).rstrip("/")
    anno = _anno_scatto(im)
    avviso = f"© {anno} {nome}"
    if sito:
        avviso += f" — {sito}"

    # Nell'EXIF ci stanno solo caratteri ASCII: il simbolo © e la lineetta
    # lunga diventerebbero due punti di domanda. Li' si scrive "(C)" e un
    # trattino normale; nell'XMP, che e' UTF-8, resta la forma per esteso.
    exif = Image.Exif()
    exif[_TAG_ARTISTA] = nome
    exif[_TAG_DIRITTI] = avviso.replace("©", "(C)").replace("—", "-")

    # XMP scritto a mano: e' un frammento fisso, e cosi' non serve
    # aggiungere una libreria in piu' solo per cinque righe di testo.
    xmp = (
        '<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description rdf:about=""'
        ' xmlns:dc="http://purl.org/dc/elements/1.1/"'
        ' xmlns:xmpRights="http://ns.adobe.com/xap/1.0/rights/"'
        ' xmlns:plus="http://ns.useplus.org/ldf/xmp/1.0/"'
        ' xmpRights:Marked="True"'
        f' xmpRights:WebStatement="{sito}/privacy">'
        f'<dc:creator><rdf:Seq><rdf:li>{nome}</rdf:li></rdf:Seq></dc:creator>'
        f'<dc:rights><rdf:Alt><rdf:li xml:lang="x-default">{avviso}</rdf:li>'
        '</rdf:Alt></dc:rights>'
        '<plus:Licensor><rdf:Seq><rdf:li rdf:parseType="Resource">'
        f'<plus:LicensorName>{nome}</plus:LicensorName>'
        f'<plus:LicensorURL>{sito}</plus:LicensorURL>'
        '</rdf:li></rdf:Seq></plus:Licensor>'
        '</rdf:Description></rdf:RDF></x:xmpmeta><?xpacket end="w"?>'
    )
    return exif.tobytes(), xmp.encode("utf-8")


def _save_jpeg(im: Image.Image, dest: Path, long_edge: int, quality: int,
               play_overlay: bool = False, formato: str = FORMATO_JPEG,
               ritaglio_social: bool = False) -> None:
    # Va letta prima del ridimensionamento: exif_transpose restituisce una
    # immagine nuova, senza i dati di partenza.
    exif_diritti, xmp_diritti = _diritti(im)

    im = ImageOps.exif_transpose(im)
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")

    if ritaglio_social:
        # Si riempie tutto il riquadro 1200x630 e si taglia via l'eccesso
        # dal centro: e' quello che fa un ritaglio "a copertura". Cosi'
        # l'anteprima non ha mai bande vuote ai lati, qualunque sia
        # l'orientamento della fotografia di partenza.
        im = ImageOps.fit(im, (SOCIAL_L, SOCIAL_H), Image.LANCZOS,
                          centering=(0.5, 0.4))
        im = im.filter(ImageFilter.UnsharpMask(radius=0.8, percent=60, threshold=3))
        tmp = dest.with_suffix(".tmp")
        im.save(tmp, format="JPEG", quality=quality, optimize=True,
                progressive=True, subsampling=2,
                exif=exif_diritti, xmp=xmp_diritti)
        tmp.replace(dest)
        return

    originale = max(im.size)
    if originale > long_edge:
        if originale > long_edge * 3:
            im.draft("RGB", (long_edge * 2, long_edge * 2))
        im.thumbnail((long_edge, long_edge), Image.LANCZOS)
        im = im.filter(ImageFilter.UnsharpMask(radius=0.8, percent=60, threshold=3))

    if play_overlay:
        _draw_play(im)

    tmp = dest.with_suffix(".tmp")
    if formato == FORMATO_WEBP:
        # A parita' di resa visiva il WebP pesa circa il 40% in meno del
        # JPEG. method=6 e' la compressione piu' accurata: piu' lenta da
        # produrre, ma le miniature si generano una volta sola.
        im.save(tmp, format="WEBP", quality=quality, method=6,
                exif=exif_diritti, xmp=xmp_diritti)
    elif formato == FORMATO_AVIF:
        # speed=6 e' il compromesso della libreria fra tempo e resa. Sulle
        # fotografie di questo sito l'AVIF a questa velocita' e' risultato
        # perfino piu' rapido del WebP a compressione accurata, quindi non
        # c'e' da rinunciare a niente.
        im.save(tmp, format="AVIF", quality=quality, speed=6,
                exif=exif_diritti, xmp=xmp_diritti)
    else:
        sub = 0 if long_edge >= 1500 else 2
        im.save(tmp, format="JPEG", quality=quality, optimize=True,
                progressive=True, subsampling=sub,
                exif=exif_diritti, xmp=xmp_diritti)
    tmp.replace(dest)


def _draw_play(im: Image.Image) -> None:
    w, h = im.size
    r = min(w, h) // 6
    cx, cy = w // 2, h // 2
    draw = ImageDraw.Draw(im, "RGBA")
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(0, 0, 0, 120))
    tri = [(cx - r // 3, cy - r // 2), (cx - r // 3, cy + r // 2), (cx + r // 2, cy)]
    draw.polygon(tri, fill=(255, 255, 255, 230))


def _thumb_from_image(source: Path, dest: Path, long_edge: int, quality: int,
                      formato: str = FORMATO_JPEG,
                      ritaglio_social: bool = False) -> bool:
    try:
        with Image.open(source) as im:
            _save_jpeg(im, dest, long_edge, quality, formato=formato,
                       ritaglio_social=ritaglio_social)
        return True
    except Exception:
        return False


def _thumb_from_video(source: Path, dest: Path, long_edge: int, quality: int,
                      formato: str = FORMATO_JPEG) -> bool:
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=True) as tmp:
            subprocess.run(
                ["ffmpeg", "-y", "-ss", "1", "-i", str(source),
                 "-frames:v", "1", "-q:v", "2", tmp.name],
                capture_output=True, timeout=60)
            if Path(tmp.name).stat().st_size == 0:
                subprocess.run(
                    ["ffmpeg", "-y", "-i", str(source),
                     "-frames:v", "1", "-q:v", "2", tmp.name],
                    capture_output=True, timeout=60)
            with Image.open(tmp.name) as im:
                _save_jpeg(im, dest, long_edge, quality, play_overlay=True,
                           formato=formato)
        return True
    except Exception:
        return False


def _scrivi(im: Image.Image, dest: Path, formato: str, quality: int,
            long_edge: int, diritti) -> None:
    """Scrive su disco un'immagine gia' ridimensionata.

    Stesse impostazioni di _save_jpeg, che pero' ridimensiona anche: qui
    l'immagine arriva gia' pronta, perche' la stessa serve a due formati.
    Il file nasce con un nome provvisorio e prende il suo solo a scrittura
    finita: se il processo venisse interrotto a meta', nella cache non
    resterebbe un file mozzo che poi verrebbe servito ai visitatori.
    """
    exif_diritti, xmp_diritti = diritti
    tmp = dest.with_suffix(".tmp")
    if formato == FORMATO_WEBP:
        im.save(tmp, format="WEBP", quality=quality, method=6,
                exif=exif_diritti, xmp=xmp_diritti)
    elif formato == FORMATO_AVIF:
        im.save(tmp, format="AVIF", quality=quality, speed=6,
                exif=exif_diritti, xmp=xmp_diritti)
    else:
        im.save(tmp, format="JPEG", quality=quality, optimize=True,
                progressive=True, subsampling=0 if long_edge >= 1500 else 2,
                exif=exif_diritti, xmp=xmp_diritti)
    tmp.replace(dest)


def prepara_gruppo(rel_path: str, mtime: float, kind: str,
                   misure, formati) -> tuple[int, int]:
    """Prepara piu' copie della stessa fotografia leggendola una volta sola.

    Chiedere le copie una per una, come fa il sito quando serve solo quella,
    significa riaprire e ridecodificare l'originale ogni volta. Preparandone
    sei in fila (tre misure per due formati) l'originale veniva letto sei
    volte dal NAS e decodificato sei volte: misurato su una fotografia da
    14 MB, 4,9 secondi in tutto, di cui 2,2 buttati a rifare sempre lo
    stesso lavoro.

    Qui si legge e si decodifica una volta sola e si lavora su copie in
    memoria. Il sito continua a usare get_or_create_thumbnail: quando serve
    una copia sola non c'e' niente da risparmiare, e conviene tenere quella
    strada semplice com'e'.

    Restituisce (fatte, non riuscite).
    """
    settings = get_settings()
    da_fare = []
    for misura in misure:
        for formato in formati:
            percorso = _cache_file(_cache_key(rel_path, mtime, misura, formato),
                                   formato)
            if not percorso.exists():
                da_fare.append((misura, formato, percorso))
    if not da_fare:
        return 0, 0

    sorgente = settings.photo_root_path / rel_path
    if not sorgente.exists():
        return 0, len(da_fare)

    fatte = errori = 0
    temporaneo = None
    try:
        if kind == "video":
            # Dal video si estrae un fotogramma solo, poi si lavora su
            # quello: chiamare ffmpeg sei volte sullo stesso filmato era la
            # parte piu' lenta di tutte.
            temporaneo = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
            temporaneo.close()
            for opzioni in (["-ss", "1"], []):
                subprocess.run(["ffmpeg", "-y", *opzioni, "-i", str(sorgente),
                                "-frames:v", "1", "-q:v", "2", temporaneo.name],
                               capture_output=True, timeout=60)
                if Path(temporaneo.name).stat().st_size > 0:
                    break
            sorgente = Path(temporaneo.name)

        # Le anteprime per le chat hanno un ritaglio tutto loro: passano
        # dalla strada normale, sono poche e non vale la pena complicare.
        social = [v for v in da_fare if v[0] == SIZE_SOCIAL]
        normali = [v for v in da_fare if v[0] != SIZE_SOCIAL]

        for misura, formato, percorso in social:
            try:
                with Image.open(sorgente) as im:
                    _save_jpeg(im, percorso, _target_long_edge(misura),
                               _quality(misura, formato), formato=formato,
                               ritaglio_social=True)
                fatte += 1
            except Exception:
                errori += 1

        if normali:
            lati = sorted({_target_long_edge(m) for m, _, _ in normali},
                          reverse=True)
            with Image.open(sorgente) as originale:
                # draft dice al decodificatore del JPEG di produrre subito
                # un'immagine piu' piccola invece di srotolare tutti i 24
                # milioni di punti per poi buttarne via il 90%. Si punta
                # alla misura piu' grande richiesta: da quella si ricavano
                # anche le altre, che sono piu' piccole.
                if max(originale.size) > lati[0] * 3:
                    originale.draft("RGB", (lati[0] * 2, lati[0] * 2))
                diritti = _diritti(originale)
                base = ImageOps.exif_transpose(originale)
                if base.mode not in ("RGB", "L"):
                    base = base.convert("RGB")

                for lato in lati:
                    # Un ridimensionamento per misura, non uno per file:
                    # WebP e AVIF della stessa misura partono dagli stessi
                    # punti gia' calcolati.
                    ridotta = base.copy()
                    if max(ridotta.size) > lato:
                        ridotta.thumbnail((lato, lato), Image.LANCZOS)
                        ridotta = ridotta.filter(ImageFilter.UnsharpMask(
                            radius=0.8, percent=60, threshold=3))
                    if kind == "video":
                        _draw_play(ridotta)
                    for misura, formato, percorso in normali:
                        if _target_long_edge(misura) != lato:
                            continue
                        try:
                            _scrivi(ridotta, percorso, formato,
                                    _quality(misura, formato), lato, diritti)
                            fatte += 1
                        except Exception:
                            errori += 1
    except Exception:
        errori += len(da_fare) - fatte
    finally:
        if temporaneo:
            Path(temporaneo.name).unlink(missing_ok=True)
    return fatte, errori


def get_or_create_thumbnail(rel_path: str, mtime: float, kind: str = "image",
                            size: str = SIZE_SMALL,
                            formato: str = FORMATO_JPEG) -> Optional[Path]:
    settings = get_settings()
    key = _cache_key(rel_path, mtime, size, formato)
    cache_file = _cache_file(key, formato)
    if cache_file.exists():
        return cache_file

    source = settings.photo_root_path / rel_path
    if not source.exists():
        return None

    long_edge = _target_long_edge(size)
    quality = _quality(size, formato)
    ok = (_thumb_from_video(source, cache_file, long_edge, quality, formato)
          if kind == "video"
          else _thumb_from_image(source, cache_file, long_edge, quality, formato,
                                 ritaglio_social=(size == SIZE_SOCIAL)))
    return cache_file if ok and cache_file.exists() else None


def clear_cache() -> int:
    settings = get_settings()
    count = 0
    if not settings.thumb_cache_path.exists():
        return 0
    for path in (list(settings.thumb_cache_path.rglob("*.jpg")) +
                 list(settings.thumb_cache_path.rglob("*.webp")) +
                 list(settings.thumb_cache_path.rglob("*.avif"))):
        try:
            path.unlink()
            count += 1
        except Exception:
            pass
    return count
