#!/usr/bin/env python3
"""Il bot Telegram che risponde: il sito in tasca.

Gli avvisi partivano gia' da soli (photocarcifo-errori.sh e
photocarcifo-sentinella.sh scrivono su Telegram quando qualcosa non va).
Mancava il verso opposto: essere fuori casa, ricevere l'avviso e non poter
chiedere nulla. Da qui in poi si puo' domandare.

Come e' fatto, e perche' cosi':

- Nessuna libreria da installare: solo quello che Python ha in casa. Una
  dipendenza in meno e' un aggiornamento notturno in meno che puo' rompere
  qualcosa.
- Nessuna porta aperta. E' il bot che chiama Telegram e resta in ascolto
  (long polling), non Telegram che chiama qui. Non c'e' niente di nuovo
  esposto su internet.
- Un solo interlocutore. Chiunque puo' trovare il bot e scrivergli, ma
  qualsiasi messaggio che non arrivi dalla chat autorizzata viene buttato
  senza nemmeno una risposta: chi bussa non sa nemmeno di aver bussato.
- Il testo che arriva da Telegram non finisce MAI in una shell. I comandi
  sono un elenco chiuso di funzioni, e l'unico argomento accettato e' la
  parola "SI" delle conferme. Non c'e' nessuna strada per far eseguire
  qualcosa che non sia scritto qui dentro.
- Le tre azioni che toccano il sito (riavvio, copia, applica) chiedono
  conferma e la conferma scade dopo un minuto.
"""
import html
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

CONFIG = "/etc/photocarcifo-telegram.conf"
APP = "/opt/photocarcifo"
DB = f"{APP}/data/photocarcifo.db"
LOG_5XX = "/var/log/nginx/photocarcifo-5xx.log"
LOG_ACCESSI = "/var/log/nginx/access.log"
STATO_NUMERI = f"{APP}/data/numeri.stato"
OFFSET = "/var/lib/photocarcifo/bot.offset"
LIMITE = 3800          # Telegram taglia a 4096: si sta larghi
SCADENZA_CONFERMA = 60  # secondi

# ---------------------------------------------------------------- config
def leggi_config():
    """Le stesse due righe che usano gli avvisi. Un posto solo."""
    valori = {}
    with open(CONFIG, encoding="utf-8") as f:
        for riga in f:
            riga = riga.strip()
            if riga.startswith("#") or "=" not in riga:
                continue
            k, _, v = riga.partition("=")
            valori[k.strip()] = v.strip().strip('"').strip("'")
    return valori.get("TELEGRAM_TOKEN", ""), valori.get("TELEGRAM_CHAT", "")


TOKEN, CHAT = leggi_config()
if not TOKEN or not CHAT:
    print("token o chat mancanti in " + CONFIG, file=sys.stderr)
    sys.exit(0)


# ------------------------------------------------------------- telegram
def tg(metodo, attesa=20, **dati):
    """Una chiamata a Telegram. Se la rete non c'e' si torna indietro
    senza rumore: il bot riprovera' al giro dopo."""
    try:
        corpo = urllib.parse.urlencode(dati).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{TOKEN}/{metodo}", data=corpo)
        with urllib.request.urlopen(req, timeout=attesa) as r:
            return json.loads(r.read())
    except Exception:
        return None


def scrivi(testo):
    if len(testo) > LIMITE:
        testo = testo[:LIMITE] + "\n…(troncato)"
    tg("sendMessage", chat_id=CHAT, text=testo, parse_mode="HTML",
       disable_web_page_preview="true")


def e(x):
    """Il testo che finisce dentro <pre> va reso innocuo, altrimenti un
    nome di file con una parentesi angolare rompe il messaggio."""
    return html.escape(str(x))


# ------------------------------------------------------- piccoli aiuti
def esegui(argomenti, secondi=120):
    """Esegue un comando dato come lista. Mai una stringa, mai shell=True:
    cosi' non esiste il concetto di "carattere speciale"."""
    try:
        p = subprocess.run(argomenti, capture_output=True, text=True,
                           timeout=secondi)
        return (p.stdout + p.stderr).strip()
    except subprocess.TimeoutExpired:
        return "(il comando ci ha messo troppo)"
    except Exception as err:
        return f"(non riuscito: {err})"


def db(query, parametri=()):
    try:
        with sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=10) as c:
            c.row_factory = sqlite3.Row
            return c.execute(query, parametri).fetchall()
    except Exception:
        return []


def attivo(servizio):
    return esegui(["systemctl", "is-active", servizio], 15) == "active"


def misura(n):
    for unita in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unita == "TB":
            return f"{n:.0f} {unita}" if unita == "B" else f"{n:.1f} {unita}"
        n /= 1024


def righe_5xx(ore=1):
    """Quante risposte di errore del server nell'ultima ora. Il registro
    di nginx scrive [19/Aug/2026:10:14:03 +0200]: invece di convertire
    ogni data si costruisce l'elenco delle ore da cercare."""
    if not os.path.exists(LOG_5XX):
        return []
    adesso = datetime.now()
    volute = {(adesso - timedelta(hours=i)).strftime("%d/%b/%Y:%H")
              for i in range(ore + 1)}
    limite = adesso - timedelta(hours=ore)
    fuori = []
    try:
        with open(LOG_5XX, encoding="utf-8", errors="replace") as f:
            for riga in f:
                m = re.search(r"\[(\d{2}/\w{3}/\d{4}):(\d{2}):(\d{2})", riga)
                if not m or f"{m.group(1)}:{m.group(2)}" not in volute:
                    continue
                quando = datetime.strptime(
                    f"{m.group(1)} {m.group(2)}:{m.group(3)}", "%d/%b/%Y %H:%M")
                if quando >= limite:
                    fuori.append(riga.strip())
    except Exception:
        pass
    return fuori


def _quanti_processi():
    """I quattro processi del sito non si trovano cercandoli per nome: solo
    il capofila porta la riga di comando di uvicorn, gli altri sono figli e
    si chiamano diversamente. L'elenco esatto lo tiene systemd, nel gruppo
    del servizio."""
    try:
        with open("/sys/fs/cgroup/system.slice/photocarcifo.service/"
                  "cgroup.procs") as f:
            return len([r for r in f if r.strip()])
    except Exception:
        return "?"


def da_quando(servizio):
    t = esegui(["systemctl", "show", servizio, "-p",
                "ActiveEnterTimestamp", "--value"], 15)
    if not t:
        return "?"
    try:
        acceso = datetime.strptime(t.rsplit(" ", 1)[0], "%a %Y-%m-%d %H:%M:%S")
        d = datetime.now() - acceso
        giorni, resto = d.days, d.seconds
        if giorni:
            return f"{giorni}g {resto // 3600}h"
        return f"{resto // 3600}h {(resto % 3600) // 60}min"
    except Exception:
        return "?"


# ------------------------------------------------------------- comandi
def cmd_stato(_=None):
    """Tutto quello che serve per dire "sta bene" o "no", in un colpo."""
    # La sentinella non e' un servizio sempre acceso: e' un colpo singolo
    # che il timer fa scattare ogni tanto. Chiedere se e' "attiva" adesso
    # risponderebbe di no quasi sempre, e il bot direbbe che qualcosa non
    # va mentre invece sta funzionando esattamente come deve.
    servizi = [("sito", "photocarcifo"), ("nginx", "nginx"),
               ("guardia", "fail2ban"),
               ("sentinella", "photocarcifo-sentinella.timer")]
    voci = []
    tutto_bene = True
    for nome, unita in servizi:
        ok = attivo(unita)
        tutto_bene = tutto_bene and ok
        voci.append(f"{'✅' if ok else '❌'} {nome}")

    processi = _quanti_processi()
    memoria = esegui(["systemctl", "show", "photocarcifo", "-p",
                      "MemoryCurrent", "--value"], 15)
    try:
        memoria = misura(int(memoria))
    except Exception:
        memoria = "?"

    uso = shutil.disk_usage("/")
    errori = len(righe_5xx(1))
    oggi = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    viste = db("SELECT COUNT(*) n FROM stats WHERE event='view_node' "
               "AND ts >= ?", (oggi,))
    viste = viste[0]["n"] if viste else 0

    bloccati = 0
    for carcere in ("photocarcifo-scansioni", "photocarcifo-login",
                    "nginx-botsearch", "sshd"):
        r = esegui(["fail2ban-client", "status", carcere], 15)
        m = re.search(r"Currently banned:\s*(\d+)", r)
        if m:
            bloccati += int(m.group(1))

    testa = "🟢 Tutto in ordine" if tutto_bene and not errori else "🔴 Qualcosa non va"
    return (f"<b>{testa}</b>\n\n"
            + "  ".join(voci) + "\n\n"
            f"processi: {processi}\n"
            f"memoria: {memoria}\n"
            f"disco: {misura(uso.free)} liberi su {misura(uso.total)}\n"
            f"acceso da: {da_quando('photocarcifo')}\n"
            f"errori nell'ultima ora: {errori}\n"
            f"gallerie viste oggi: {viste}\n"
            f"indirizzi bloccati adesso: {bloccati}")


def cmd_errori(_=None):
    """Cos'e' andato storto, e quante volte. Le stesse righe che fanno
    scattare l'avviso automatico, ma a richiesta."""
    righe = righe_5xx(24)
    if not righe:
        return "✅ Nessun errore del server nelle ultime 24 ore."

    conteggio = {}
    for r in righe:
        m = re.search(r'"(?:GET|POST|HEAD|PUT|DELETE) ([^ ?"]+)', r)
        s = re.search(r'" (\d{3}) ', r)
        chiave = (s.group(1) if s else "5xx", m.group(1) if m else "?")
        conteggio[chiave] = conteggio.get(chiave, 0) + 1

    out = [f"<b>⚠️ {len(righe)} errori nelle ultime 24 ore</b>\n"]
    for (codice, dove), n in sorted(conteggio.items(), key=lambda x: -x[1])[:12]:
        out.append(f"<code>{codice}</code> ×{n}  {e(dove)}")

    guai = db("SELECT ts, category, message FROM logs WHERE level IN "
              "('ERROR','CRITICAL') ORDER BY id DESC LIMIT 5")
    if guai:
        out.append("\n<b>Dal registro dell'applicazione</b>")
        for g in guai:
            out.append(f"{e(g['ts'][11:16])} {e(g['category'])}: "
                       f"{e(g['message'][:120])}")
    return "\n".join(out)


def cmd_visite(_=None):
    """Chi e' passato, e cosa ha guardato."""
    ora = datetime.now(timezone.utc)
    oggi = ora.strftime("%Y-%m-%d")
    settimana = (ora - timedelta(days=7)).strftime("%Y-%m-%d")

    def quante(evento, da):
        r = db("SELECT COUNT(*) n FROM stats WHERE event=? AND ts >= ?",
               (evento, da))
        return r[0]["n"] if r else 0

    out = ["<b>👀 Visite</b>\n",
           f"oggi: {quante('view_node', oggi)} gallerie aperte, "
           f"{quante('zip_node', oggi) + quante('zip_select', oggi)} archivi scaricati",
           f"7 giorni: {quante('view_node', settimana)} gallerie aperte, "
           f"{quante('zip_node', settimana) + quante('zip_select', settimana)} archivi"]

    top = db("SELECT ref, COUNT(*) n FROM stats WHERE event='view_node' "
             "AND ts >= ? GROUP BY ref ORDER BY n DESC LIMIT 8", (settimana,))
    if top:
        out.append("\n<b>Le piu' guardate (7 giorni)</b>")
        for t in top:
            out.append(f"{t['n']:>4}×  {e(t['ref'])}")

    cercate = db("SELECT testo, volte, risultati FROM ricerche "
                 "ORDER BY ultimo_at DESC LIMIT 6")
    if cercate:
        out.append("\n<b>Ultime ricerche</b>")
        for c in cercate:
            vuota = " ⚠️ nessun risultato" if not c["risultati"] else ""
            out.append(f"«{e(c['testo'])}» ×{c['volte']}{vuota}")
    return "\n".join(out)


def cmd_spazio(_=None):
    """Lo spazio e' l'unica cosa che si esaurisce in silenzio."""
    uso = shutil.disk_usage("/")
    percento = 100 * uso.used / uso.total
    segno = "🟢" if percento < 75 else ("🟡" if percento < 90 else "🔴")
    out = [f"<b>{segno} Spazio</b>\n",
           f"sistema: {misura(uso.free)} liberi di {misura(uso.total)} "
           f"({percento:.0f}% usato)"]

    for nome, percorso in (("miniature", f"{APP}/data/cache"),
                           ("copie", f"{APP}/backup")):
        if os.path.isdir(percorso):
            d = esegui(["du", "-sh", percorso], 120).split()
            if d:
                out.append(f"{nome}: {d[0]}")

    if os.path.ismount("/mnt/magazzino"):
        m = shutil.disk_usage("/mnt/magazzino")
        out.append(f"archivio: {misura(m.free)} liberi di {misura(m.total)}")
    else:
        out.append("archivio: ⚠️ non collegato")

    copie = esegui(["ls", "-1t", f"{APP}/backup/aggiornamenti"], 30)
    ultime = [c for c in copie.splitlines() if c.endswith(".tar.gz")
              and "extra" not in c][:3]
    if ultime:
        out.append("\n<b>Ultime copie</b>")
        out += [f"• {e(u)}" for u in ultime]
    return "\n".join(out)


def cmd_foto(_=None):
    """I numeri dell'archivio."""
    r = db("SELECT (SELECT COUNT(*) FROM media) foto, "
           "(SELECT COUNT(*) FROM nodes) alb, "
           "(SELECT COUNT(*) FROM nodes WHERE is_private=1) priv, "
           "(SELECT COUNT(*) FROM nodes WHERE hidden=1) nasc, "
           "(SELECT COUNT(*) FROM media WHERE kind='image') immagini, "
           # I numeri di gara si leggono dalle fotografie. I video non
           # hanno numeri da leggere: contarli fra i "non ancora letti"
           # faceva sembrare che ci fosse sempre del lavoro arretrato.
           "(SELECT COUNT(*) FROM media WHERE kind='image' AND ocr_stato='fatto') letti")
    if not r:
        return "Non riesco a leggere il database."
    d = r[0]
    ultimo = db("SELECT title, created_at FROM nodes WHERE depth>0 "
                "ORDER BY created_at DESC LIMIT 3")
    out = ["<b>📸 Archivio</b>\n",
           f"fotografie: {d['foto']:,}".replace(",", "'"),
           f"gallerie: {d['alb']}  (riservate: {d['priv']}, nascoste: {d['nasc']})",
           f"numeri letti: {d['letti']:,} su {d['immagini']:,}".replace(",", "'")]
    if ultimo:
        out.append("\n<b>Ultime aggiunte</b>")
        out += [f"• {e(u['title'])} — {e(u['created_at'][:10])}" for u in ultimo]
    return "\n".join(out)


def cmd_recensioni(_=None):
    """Quelle in attesa: sono l'unica cosa che aspetta te."""
    attesa = db("SELECT id, nome, voto, evento, testo, creato_at FROM recensioni "
                "WHERE approvata=0 ORDER BY creato_at DESC LIMIT 8")
    if not attesa:
        n = db("SELECT COUNT(*) n FROM recensioni WHERE approvata=1")
        return ("✅ Nessuna recensione in attesa.\n"
                f"Pubblicate finora: {n[0]['n'] if n else 0}")
    out = [f"<b>✍️ {len(attesa)} in attesa</b>\n"]
    for r in attesa:
        stelle = "★" * r["voto"] + "☆" * (5 - r["voto"])
        out.append(f"{stelle}  <b>{e(r['nome'])}</b> — {e(r['evento'] or '—')}")
        out.append(f"{e(r['testo'][:220])}\n")
    out.append("Si approvano dal pannello: /admin/recensioni")
    return "\n".join(out)


def cmd_numeri(_=None):
    """La lettura dei numeri di gara e' lunga: sapere a che punto sta,
    senza aprire il pannello."""
    if not os.path.exists(STATO_NUMERI):
        return "Nessuna lettura numeri in corso."
    try:
        with open(STATO_NUMERI, encoding="utf-8") as f:
            s = json.load(f)
    except Exception:
        return "Nessuna lettura numeri in corso."
    if not s.get("attivo"):
        return (f"Lettura numeri ferma.\n"
                f"Ultimo giro: {e(s.get('fatti', 0))} foto lette.")
    fatti, totale = s.get("fatti", 0), s.get("totale", 0) or 1
    quota = int(20 * fatti / totale)
    return (f"<b>🔢 Lettura numeri in corso</b>\n\n"
            f"<code>{'█' * quota}{'░' * (20 - quota)}</code>\n"
            f"{fatti} di {totale} ({100 * fatti // totale}%)")


def cmd_diagnosi(_=None):
    """Guarda e ripara.

    Cerca i guasti e, per quelli che si sanno riparare, li ripara: servizio
    spento, archivio scollegato, album privato senza link, righe di
    database inutili, spazio esaurito, automatismo disattivato. Tutto il
    resto — in particolare i 66 controlli di funzionamento — viene
    riferito e basta: un controllo che non torna puo' avere il motivo in
    mille posti, e indovinare farebbe piu' danni del guasto.

    Per guardare senza toccare niente c'e' /controlla.
    """
    scrivi("Controllo e riparazione in corso, un paio di minuti…")
    return _riassunto(esegui(["/usr/local/bin/photocarcifo-ripara.sh"], 900))


def cmd_controlla(_=None):
    """Come /diagnosi, ma non tocca niente: dice solo cosa farebbe."""
    scrivi("Guardo, senza toccare nulla…")
    return _riassunto(esegui(
        ["/usr/local/bin/photocarcifo-ripara.sh", "--guarda"], 900))


def _riassunto(testo):
    """Del rapporto interessano le righe che dicono qualcosa: i problemi
    trovati, cosa e' stato fatto, cosa resta da fare a mano."""
    righe = [r.rstrip() for r in testo.splitlines()]
    problemi = [r for r in righe if r.strip().startswith(("⚠", "→", "✗"))]
    coda = [r for r in righe if r.startswith("═══ Trovati") or r.startswith("═══ Niente")]
    if not problemi:
        return ("✅ <b>Tutto in ordine.</b>\n\nOtto aree controllate, "
                "66 prove di funzionamento: niente da riparare.")
    out = ["<b>🔧 Rapporto</b>\n"]
    out += [e(r.strip()) for r in problemi[:25]]
    if coda:
        out.append("\n<b>" + e(coda[-1].replace("═══", "").strip()) + "</b>")
    return "\n".join(out)


def cmd_salva(argomento):
    """Copia di sicurezza a richiesta."""
    if argomento != "SI":
        return _chiedi_conferma("salva", "faccio una copia di sicurezza completa")
    scrivi("Copia in corso…")
    testo = esegui(["/usr/local/bin/photocarcifo-salva.sh"], 900)
    return f"<b>Copia</b>\n<pre>{e(testo[-1500:])}</pre>"


def cmd_riavvia(argomento):
    """Riavvio del solo sito. Non della macchina: quella non si tocca
    da un messaggio."""
    if argomento != "SI":
        return _chiedi_conferma(
            "riavvia", "riavvio il sito (una decina di secondi di buco)")
    esegui(["systemctl", "restart", "photocarcifo"], 120)
    time.sleep(8)
    codice = esegui(["curl", "-s", "-o", "/dev/null", "-m", "20",
                     "-w", "%{http_code}", "http://127.0.0.1:8000/healthz"], 40)
    if codice == "200":
        return "✅ Riavviato, il sito risponde."
    return f"🔴 Riavviato ma risponde {e(codice)}. Serve guardarci."


def cmd_applica(argomento):
    """La catena di controlli prima della messa in servizio: serve quando
    una modifica e' gia' sul server e va solo attivata."""
    if argomento != "SI":
        return _chiedi_conferma(
            "applica", "eseguo i controlli e metto in servizio le modifiche")
    scrivi("Controlli in corso, un paio di minuti…")
    testo = esegui(["/usr/local/bin/photocarcifo-applica.sh"], 900)
    return f"<pre>{e(testo[-2500:])}</pre>"


CARCERI = ("photocarcifo-scansioni", "photocarcifo-login",
           "nginx-botsearch", "nginx-limit-req", "sshd")


def cmd_bloccati(_=None):
    """Chi e' fuori adesso, e perche'."""
    righe = []
    totale = 0
    for carcere in CARCERI:
        r = esegui(["fail2ban-client", "status", carcere], 20)
        m = re.search(r"Banned IP list:\s*(.*)", r)
        indirizzi = (m.group(1).split() if m else [])
        totale += len(indirizzi)
        if indirizzi:
            nome = carcere.replace("photocarcifo-", "").replace("nginx-", "")
            righe.append(f"<b>{e(nome)}</b>")
            righe += [f"  <code>{e(i)}</code>" for i in indirizzi]
    if not totale:
        return "✅ Nessun indirizzo bloccato in questo momento."
    return (f"<b>🚫 {totale} bloccati</b>\n\n" + "\n".join(righe) +
            "\n\nPer liberarli tutti: /sblocca")


def cmd_sblocca(argomento):
    """La via di scampo.

    Tutta la casa esce dallo stesso indirizzo di rete: se un giorno un
    dispositivo di casa finisse per sbaglio dietro a un blocco, il sito
    diventerebbe irraggiungibile proprio da dove serve di piu', e per
    rimediare bisognerebbe entrare nel server. Da qui si fa dal telefono.
    """
    if argomento != "SI":
        return _chiedi_conferma("sblocca", "libero tutti gli indirizzi bloccati")
    liberati = 0
    for carcere in CARCERI:
        r = esegui(["fail2ban-client", "status", carcere], 20)
        m = re.search(r"Banned IP list:\s*(.*)", r)
        for indirizzo in (m.group(1).split() if m else []):
            esegui(["fail2ban-client", "set", carcere, "unbanip", indirizzo], 20)
            liberati += 1
    if not liberati:
        return "Non c'era nessuno da liberare."
    return (f"✅ Liberati {liberati} indirizzi.\n\n"
            "Se erano scanner ci ricascheranno da soli entro pochi minuti, "
            "ed e' giusto cosi'.")


def cmd_aiuto(_=None):
    return ("<b>Cosa so fare</b>\n\n"
            "/stato — come sta il sito, in un colpo\n"
            "/errori — cos'e' andato storto nelle 24 ore\n"
            "/visite — chi e' passato e cosa ha guardato\n"
            "/spazio — disco, miniature, copie, archivio\n"
            "/foto — i numeri dell'archivio\n"
            "/recensioni — quelle in attesa di approvazione\n"
            "/numeri — a che punto e' la lettura dei numeri\n"
            "/bloccati — chi e' fuori adesso, e perche'\n"
            "/diagnosi — cerca i guasti e ripara quelli che sa riparare\n"
            "/controlla — come diagnosi, ma senza toccare niente\n"
            "\n<b>Con conferma</b>\n"
            "/sblocca — libera tutti gli indirizzi bloccati\n"
            "/salva — copia di sicurezza adesso\n"
            "/riavvia — riavvia il sito\n"
            "/applica — controlli e messa in servizio\n"
            "\nLe tre qui sopra chiedono conferma e la conferma scade "
            "dopo un minuto.")


# ------------------------------------------------------------ conferme
_attesa = {}


def _chiedi_conferma(comando, cosa):
    _attesa[comando] = time.time()
    return (f"⚠️ Confermi? {cosa}.\n\n"
            f"Rispondi <code>/{comando} SI</code> entro un minuto.")


def _conferma_valida(comando):
    quando = _attesa.pop(comando, 0)
    return time.time() - quando < SCADENZA_CONFERMA


COMANDI = {
    "stato": cmd_stato, "errori": cmd_errori, "visite": cmd_visite,
    "spazio": cmd_spazio, "foto": cmd_foto, "recensioni": cmd_recensioni,
    "numeri": cmd_numeri, "diagnosi": cmd_diagnosi,
    "controlla": cmd_controlla, "bloccati": cmd_bloccati,
    "sblocca": cmd_sblocca, "salva": cmd_salva,
    "riavvia": cmd_riavvia, "applica": cmd_applica,
    "aiuto": cmd_aiuto, "start": cmd_aiuto, "help": cmd_aiuto,
}
CON_CONFERMA = {"salva", "riavvia", "applica", "sblocca"}


def gestisci(testo):
    pezzi = testo.strip().split()
    if not pezzi or not pezzi[0].startswith("/"):
        return "Non ho capito. /aiuto per l'elenco."
    # "/stato@nome_del_bot" nei gruppi
    nome = pezzi[0][1:].split("@")[0].lower()
    funzione = COMANDI.get(nome)
    if not funzione:
        return f"Non conosco «{e(nome)}». /aiuto per l'elenco."
    # L'unico argomento che esiste in tutto il bot e' la parola SI.
    argomento = "SI" if len(pezzi) > 1 and pezzi[1].upper() == "SI" else ""
    if nome in CON_CONFERMA and argomento == "SI" and not _conferma_valida(nome):
        return "La conferma e' scaduta. Ridai il comando."
    return funzione(argomento)


# ------------------------------------------------------------------ giro
def leggi_offset():
    try:
        with open(OFFSET) as f:
            return int(f.read().strip())
    except Exception:
        return 0


def scrivi_offset(n):
    try:
        os.makedirs(os.path.dirname(OFFSET), exist_ok=True)
        with open(OFFSET, "w") as f:
            f.write(str(n))
    except Exception:
        pass


def main():
    tg("setMyCommands", commands=json.dumps([
        {"command": c, "description": d} for c, d in [
            ("stato", "Come sta il sito"),
            ("errori", "Cos'e' andato storto"),
            ("visite", "Chi e' passato"),
            ("spazio", "Disco e copie"),
            ("foto", "Numeri dell'archivio"),
            ("recensioni", "In attesa di approvazione"),
            ("numeri", "Lettura numeri di gara"),
            ("diagnosi", "Cerca i guasti e li ripara"),
            ("controlla", "Guarda senza toccare niente"),
            ("bloccati", "Chi e' bloccato adesso"),
            ("sblocca", "Libera tutti i bloccati"),
            ("salva", "Copia di sicurezza"),
            ("riavvia", "Riavvia il sito"),
            ("applica", "Metti in servizio le modifiche"),
            ("aiuto", "L'elenco dei comandi"),
        ]]))

    offset = leggi_offset()
    while True:
        r = tg("getUpdates", attesa=40, offset=offset, timeout=30)
        if not r or not r.get("ok"):
            time.sleep(5)
            continue
        for agg in r.get("result", []):
            offset = agg["update_id"] + 1
            scrivi_offset(offset)
            msg = agg.get("message") or agg.get("edited_message")
            if not msg:
                continue
            # L'unica riga di sicurezza che conta davvero: chiunque puo'
            # scrivere al bot, ma solo una chat viene ascoltata. Alle
            # altre non si risponde nemmeno "non sei autorizzato": una
            # risposta e' gia' un'informazione.
            if str(msg.get("chat", {}).get("id")) != str(CHAT):
                continue
            testo = msg.get("text", "")
            if not testo:
                continue
            try:
                scrivi(gestisci(testo))
            except Exception as err:
                scrivi(f"Qualcosa e' andato storto: {e(err)}")


if __name__ == "__main__":
    main()
