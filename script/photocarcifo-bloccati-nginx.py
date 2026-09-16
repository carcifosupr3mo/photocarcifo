#!/usr/bin/env python3
"""Da "bannato da fail2ban" a "vede la pagina di blocco".

Il problema che risolve. Le jail di questo sito bannavano scrivendo una
regola nel firewall (iptables-multiport -> nftables reject): la
connessione non si apriva nemmeno, e chi era bloccato vedeva il browser
girare a vuoto e poi un errore di rete. Per un vero attacco va benissimo.
Per una persona che ha sbagliato tre volte la password di un album, o che
ha sfogliato troppo in fretta, e' il modo peggiore di dirlo: sembra che il
sito sia rotto, non che sia lei a essere stata fermata.

Come funziona adesso, per le sole jail del sito (vedi jail.d/
photocarcifo.local): fail2ban non tocca piu' il firewall, chiama questo
script, che tiene aggiornato un elenco di indirizzi che nginx legge con
una direttiva geo. Nginx risponde a quegli indirizzi con la pagina di
blocco, qualunque cosa chiedano. Il traffico arriva fino a nginx e si
ferma li': l'applicazione non lo vede mai.

Chi resta padrone dello stato dei ban e' sempre fail2ban — scadenze,
persistenza fra riavvii, /bloccati, /sblocca, /banip, /unbanip continuano
a leggere e scrivere li'. Questo script non decide niente: rispecchia.
Per questo lo stato locale e' tenuto per jail (una cartella per jail, un
file per indirizzo): quando fail2ban riparte e riapplica i ban salvati
chiama actionstart e poi un actionban per ciascuno, e la cartella si
ricostruisce da sola senza portarsi dietro i ban scaduti nel frattempo.

La regola che questo script non deve violare mai: **non lasciare nginx
con una configurazione che non parte**. Un ban in meno e' un fastidio; il
sito giu' per tutti perche' si e' aggiunto un indirizzo e' un disastro.
Quindi si scrive un file temporaneo, si mette al posto giusto in modo
atomico, si chiede a nginx se la configurazione gli va bene, e se non gli
va bene si rimette esattamente com'era prima e non si ricarica niente.
"""
import fcntl
import ipaddress
import os
import re
import subprocess
import sys
import time
from datetime import datetime

# Lo stato: una cartella per jail, un file vuoto per indirizzo bloccato.
# Sta in /var/lib e non in /etc perche' e' stato che cambia da solo, non
# configurazione scritta da una persona.
STATO = "/var/lib/photocarcifo/bloccati"

# La cartella che nginx include con una stella (vedi snippets/
# photocarcifo-bloccati.conf). Una stella e non un nome preciso apposta:
# se il file non c'e' — primo avvio, container appena ricostruito da un
# backup — nginx parte lo stesso con zero indirizzi bloccati. Con un nome
# preciso, invece, un file mancante impedirebbe a nginx di partire, e il
# sito sarebbe giu' per tutti per colpa di un elenco vuoto.
USCITA_DIR = "/etc/nginx/photocarcifo-bloccati.d"
USCITA = os.path.join(USCITA_DIR, "bloccati.conf")

LOCK = "/var/lib/photocarcifo/bloccati.lock"
LOG = "/var/lib/photocarcifo/bloccati.log"


def loga(riga):
    """Chi e' stato bloccato o liberato, da quale jail, e se la
    sincronizzazione con nginx e' riuscita. Nessun token, nessun
    indirizzo di pagina privata: solo l'indirizzo IP e l'esito."""
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')} {riga}\n")
    except OSError:
        pass  # un log che non si scrive non deve fermare un ban


def indirizzo_valido(testo):
    """L'indirizzo arriva da fail2ban, non da un estraneo, ma finisce in
    un file di configurazione di nginx: se ci passasse una riga inventata
    nginx non ripartirebbe. ipaddress e' l'unico giudice — niente regex.

    Si rifiutano anche gli indirizzi interni: bloccare 192.168.x
    vorrebbe dire mostrare la pagina di blocco a tutta la casa, e la
    stessa protezione c'e' gia' in /banip e in ignoreip. Qui e' l'ultima
    rete di sicurezza prima del file che nginx legge davvero."""
    try:
        ip = ipaddress.ip_address(testo)
    except ValueError:
        return None
    if (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_multicast or ip.is_unspecified or ip.is_reserved
            or not ip.is_global):
        return None
    return ip


def _cartella_jail(jail):
    """Il nome della jail viene da fail2ban, ma finisce in un percorso.

    basename() da solo NON basta: basename("..") e' "..", e una jail
    chiamata cosi' avrebbe fatto svuotare /var/lib/photocarcifo — cioe'
    lo storico dei ban, la coda Telegram, i log. Non e' una via aperta a
    un estraneo (il nome viene da jail.d, non dalla rete), ma un refuso
    basterebbe: si accetta solo un nome che sia davvero un nome."""
    sicuro = os.path.basename(jail).strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", sicuro or "") or sicuro in (".", ".."):
        sicuro = "senza-nome"
    return os.path.join(STATO, sicuro)


def elenco_indirizzi():
    """Tutti gli indirizzi bloccati, di tutte le jail, senza ripetizioni:
    lo stesso indirizzo puo' essere finito in due jail diverse, per nginx
    e' bloccato una volta sola."""
    trovati = set()
    if not os.path.isdir(STATO):
        return trovati
    for jail in sorted(os.listdir(STATO)):
        cartella = os.path.join(STATO, jail)
        if not os.path.isdir(cartella):
            continue
        for nome in os.listdir(cartella):
            if indirizzo_valido(nome):
                trovati.add(nome)
    return trovati


def testo_elenco(indirizzi):
    """Il contenuto del file che nginx legge. Separato dalla scrittura
    perche' chi chiama deve poterlo confrontare con quello di prima senza
    aver gia' toccato niente sul disco."""
    # Nessun orario qui dentro: due elenchi con gli stessi indirizzi
    # devono risultare IDENTICI, altrimenti il confronto in rigenera()
    # non potrebbe mai evitare una ricarica inutile. Quando e' cambiato
    # sta nel log, con piu' contesto.
    righe = ["# Generato da photocarcifo-bloccati-nginx.py — non modificare a mano.",
             f"# {len(indirizzi)} indirizzi bloccati."]
    for ip in sorted(indirizzi, key=lambda x: (":" in x, x)):
        righe.append(f"{ip} 1;")
    return "\n".join(righe) + "\n"


def scrivi_elenco(testo):
    """Scritto a fianco e poi spostato: nginx potrebbe stare leggendo
    proprio ora, e uno spostamento nella stessa cartella o e' avvenuto o
    non e' avvenuto — non esiste il mezzo file."""
    os.makedirs(USCITA_DIR, exist_ok=True)
    temporaneo = USCITA + ".nuovo"
    with open(temporaneo, "w", encoding="utf-8") as f:
        f.write(testo)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporaneo, USCITA)


def nginx_approva():
    """Non solleva mai: chi chiama deve poter tornare indietro anche
    quando nginx non risponde affatto. Un'eccezione qui lascerebbe al suo
    posto un file che nessuno ha convalidato — proprio nel caso in cui
    non si sa se va bene."""
    try:
        r = subprocess.run(["nginx", "-t"], capture_output=True, text=True,
                           timeout=30)
    except subprocess.TimeoutExpired:
        return False, "nginx -t non ha risposto entro trenta secondi"
    except OSError as errore:
        return False, f"nginx -t non eseguibile: {errore}"
    return r.returncode == 0, (r.stdout + r.stderr).strip()


def rigenera():
    """Rispecchia lo stato in nginx. Torna True se nginx ha la lista
    aggiornata e funzionante, False se si e' dovuto tornare indietro.

    Tre cose che devono valere sempre, in quest'ordine di importanza:
    non lasciare mai al suo posto un file che nginx non ha approvato
    (nemmeno uscendo per un'eccezione: per questo il ripristino sta in un
    finally); non ricaricare una configurazione rifiutata; non ricaricare
    per niente quando l'elenco non e' cambiato."""
    precedente = None
    if os.path.exists(USCITA):
        try:
            with open(USCITA, encoding="utf-8") as f:
                precedente = f.read()
        except OSError:
            precedente = None

    try:
        nuovo = testo_elenco(elenco_indirizzi())
    except OSError as errore:
        loga(f"SINCRONIZZAZIONE FALLITA, stato illeggibile: {errore}")
        return False

    # Stessi indirizzi di prima: non c'e' niente da dire a nginx. Senza
    # questo, l'avvio di fail2ban con quattro jail faceva quattro
    # ricariche identiche di fila, e ogni ricarica lascia in vita i
    # vecchi worker finche' non chiudono le loro connessioni — su un sito
    # dove si scaricano album interi, non e' gratis.
    if precedente == nuovo:
        return "invariato"

    convalidato = False
    try:
        scrivi_elenco(nuovo)
        va_bene, dettaglio = nginx_approva()
        if not va_bene:
            loga("SINCRONIZZAZIONE FALLITA, configurazione precedente "
                 "ripristinata: " + (dettaglio.splitlines()[-1] if dettaglio
                                     else "nginx -t senza dettagli"))
            return False
        convalidato = True
    except OSError as errore:
        loga(f"SINCRONIZZAZIONE FALLITA, file non scrivibile: {errore}")
        return False
    finally:
        # Qualunque cosa sia andata storta — anche un'eccezione che qui
        # non si e' nemmeno provato a prevedere — il file torna com'era:
        # non deve mai restare in giro un elenco che nginx non ha visto.
        if not convalidato:
            _ripristina(precedente)

    r = _reload_nginx()
    if r is not True:
        loga(f"RICARICA NGINX FALLITA: {r}")
        return False
    return True


def _ripristina(precedente):
    try:
        if precedente is None:
            if os.path.exists(USCITA):
                os.remove(USCITA)
        else:
            temporaneo = USCITA + ".nuovo"
            with open(temporaneo, "w", encoding="utf-8") as f:
                f.write(precedente)
            os.replace(temporaneo, USCITA)
    except OSError as errore:
        loga(f"RIPRISTINO FALLITO: {errore}")


def _reload_nginx():
    """True se ricaricato, altrimenti il motivo. Il tempo massimo e'
    corto apposta: allo spegnimento della macchina fail2ban ferma le sue
    jail una per una e systemd non aspetta all'infinito — meglio
    rinunciare a una ricarica che far uccidere fail2ban a meta'."""
    try:
        r = subprocess.run(["systemctl", "reload", "nginx"],
                           capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired:
        return "systemctl reload non ha risposto entro quindici secondi"
    except OSError as errore:
        return f"systemctl non eseguibile: {errore}"
    if r.returncode != 0:
        return (r.stderr or r.stdout).strip()[:200]
    return True


def blocca(jail, ip):
    valido = indirizzo_valido(ip)
    if not valido:
        loga(f"RIFIUTATO {ip} (jail {jail}): non e' un indirizzo pubblico valido")
        return 0  # non e' un errore di fail2ban: semplicemente non si scrive
    cartella = _cartella_jail(jail)
    percorso = os.path.join(cartella, str(valido))
    try:
        os.makedirs(cartella, exist_ok=True)
        with open(percorso, "w"):
            pass
    except OSError as errore:
        loga(f"BLOCCO NON REGISTRATO {valido} (jail {jail}): {errore}")
        return 1
    esito = rigenera()
    if not esito:
        # Lo stato locale non deve raccontare una cosa diversa da quella
        # che nginx sta applicando davvero: se la sincronizzazione non e'
        # riuscita, questo indirizzo non e' bloccato, e lo stato deve
        # dirlo. Altrimenti la prossima rigenerazione riuscita lo
        # rimetterebbe dentro senza che nessuno l'abbia piu' chiesto.
        _dimentica(percorso)
    loga(f"BLOCCATO {valido} (jail {jail}) — {_esito(esito)}")
    return 0 if esito else 1


def libera(jail, ip):
    valido = indirizzo_valido(ip)
    if not valido:
        return 0
    percorso = os.path.join(_cartella_jail(jail), str(valido))
    c_era = os.path.exists(percorso)
    _dimentica(percorso)
    esito = rigenera()
    if not esito and c_era:
        # Il caso peggiore di tutti: fail2ban non richiama mai
        # actionunban, quindi se lo stato dimenticasse l'indirizzo mentre
        # nginx continua a bloccarlo, quella persona resterebbe sulla
        # pagina di blocco per sempre, e nessuna rigenerazione futura
        # potrebbe accorgersene. Si rimette com'era: cosi' il prossimo
        # tentativo riuscito lo toglie davvero.
        try:
            with open(percorso, "w"):
                pass
        except OSError:
            loga(f"ATTENZIONE: {valido} tolto dallo stato ma forse ancora "
                 f"bloccato in nginx — controllare con 'rigenera'")
    loga(f"LIBERATO {valido} (jail {jail}) — {_esito(esito)}")
    return 0 if esito else 1


def _esito(esito):
    """Tre esiti, non due: "gia' cosi'" non e' un fallimento, ed e' il
    caso piu' frequente (l'avvio di fail2ban lo attraversa una volta per
    jail). Distinguerlo nel log serve a vedere quante ricariche di nginx
    stiamo davvero facendo."""
    if esito == "invariato":
        return "nginx gia' aggiornato, nessuna ricarica"
    return "nginx aggiornato" if esito else "nginx NON aggiornato"


def _dimentica(percorso):
    try:
        os.remove(percorso)
    except OSError:
        pass  # non c'era: il risultato voluto e' gia' quello


def svuota(jail):
    """Tutti gli indirizzi di UNA jail, non di tutte: le altre jail hanno
    i loro e non c'entrano niente."""
    cartella = _cartella_jail(jail)
    quanti = 0
    if os.path.isdir(cartella):
        for nome in os.listdir(cartella):
            try:
                os.remove(os.path.join(cartella, nome))
                quanti += 1
            except OSError:
                pass
    esito = rigenera()
    loga(f"SVUOTATA jail {jail} ({quanti} indirizzi) — {_esito(esito)}")
    return 0 if esito else 1


def main():
    if len(sys.argv) < 2:
        print("uso: photocarcifo-bloccati-nginx.py "
              "blocca|libera|svuota|avvia|ferma|rigenera <jail> [ip]",
              file=sys.stderr)
        return 2
    azione = sys.argv[1]
    jail = sys.argv[2] if len(sys.argv) > 2 else ""
    ip = sys.argv[3] if len(sys.argv) > 3 else ""

    os.makedirs(os.path.dirname(LOCK), exist_ok=True)
    # Due ban nello stesso istante da jail diverse riscriverebbero lo
    # stesso file: si aspetta il proprio turno invece di sovrapporsi.
    #
    # Ma si aspetta con una scadenza, non all'infinito: fail2ban esegue
    # actionunban dentro il filo che serve il comando, quindi un
    # /unbanip dal telefono resterebbe appeso finche' dura il ban di
    # qualcun altro. In condizioni normali qui si aspettano millisecondi
    # (nginx -t misura una ventina); se davvero passano quindici secondi
    # e' successo qualcosa di grosso, e rinunciare lasciando una riga nel
    # log e' meglio che restare fermi.
    with open(LOCK, "w") as blocco:
        scadenza = time.monotonic() + 15
        while True:
            try:
                fcntl.flock(blocco, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= scadenza:
                    loga(f"RINUNCIA: un'altra sincronizzazione tiene il "
                         f"lucchetto da troppo tempo ({azione} {jail} {ip})".strip())
                    return 1
                time.sleep(0.2)
        if azione == "blocca":
            return blocca(jail, ip)
        if azione == "libera":
            return libera(jail, ip)
        # "avvia" e "svuota" fanno la stessa cosa: quando una jail parte,
        # i suoi indirizzi di prima non valgono piu' — fail2ban sta per
        # riapplicare quelli veri, uno per uno, e quelli scaduti mentre
        # era spento devono sparire.
        if azione in ("avvia", "svuota", "ferma"):
            return svuota(jail)
        if azione == "rigenera":
            return 0 if rigenera() else 1
        print(f"azione sconosciuta: {azione}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
