"""La sincronizzazione fail2ban -> nginx (script/photocarcifo-bloccati-nginx.py).

Lo script decide cosa finisce nel file che nginx legge per sapere chi e'
bloccato: se ci finisse una riga sbagliata, nginx non ripartirebbe e il
sito sarebbe giu' per tutti. Questi test guardano proprio quel punto —
quali indirizzi passano, come viene scritto il file, e soprattutto che una
configurazione rifiutata da nginx non lasci mai il file rotto al suo posto.

Nginx vero non viene mai chiamato: `nginx -t` e il ricaricamento sono
sostituiti, come si fa nel resto della suite con i comandi di sistema. Il
comportamento con nginx vero e' stato verificato a mano sul sistema (ban
di un indirizzo di documentazione legato al loopback, navigazione bloccata
su ogni percorso, rollback provato rompendo la configurazione di
proposito): quello che si controlla qui e' la logica, non il sistema.
"""
import importlib.util
from pathlib import Path

import pytest

RADICE = Path(__file__).resolve().parent.parent
SCRIPT = RADICE / "script" / "photocarcifo-bloccati-nginx.py"


def _carica_modulo():
    """Nome con i trattini: non importabile direttamente, si carica dal
    percorso (stessa ragione e stesso modo di test_bot_telegram.py)."""
    spec = importlib.util.spec_from_file_location("photocarcifo_bloccati", SCRIPT)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture
def sync(monkeypatch, tmp_path):
    """Lo script con tutti i percorsi spostati in una cartella
    temporanea: nessun test tocca /etc/nginx o /var/lib veri. nginx viene
    sostituito da un finto che risponde sempre di si' e registra le
    chiamate; i test che vogliono un rifiuto se lo impostano da soli."""
    modulo = _carica_modulo()
    monkeypatch.setattr(modulo, "STATO", str(tmp_path / "stato"))
    monkeypatch.setattr(modulo, "USCITA_DIR", str(tmp_path / "nginx.d"))
    monkeypatch.setattr(modulo, "USCITA", str(tmp_path / "nginx.d" / "bloccati.conf"))
    monkeypatch.setattr(modulo, "LOCK", str(tmp_path / "blocco.lock"))
    monkeypatch.setattr(modulo, "LOG", str(tmp_path / "registro.log"))

    modulo._approva = True
    modulo._ricaricato = []
    monkeypatch.setattr(modulo, "nginx_approva",
                        lambda: (modulo._approva, "" if modulo._approva else "prova: config rifiutata"))

    modulo._reload_ok = True

    def finta_reload(argomenti, **kwargs):
        modulo._ricaricato.append(list(argomenti))

        class Esito:
            returncode = 0 if modulo._reload_ok else 1
            stdout = ""
            stderr = "systemctl finto: ricarica non riuscita"
        return Esito()

    monkeypatch.setattr(modulo.subprocess, "run", finta_reload)
    return modulo


def _contenuto(sync):
    return Path(sync.USCITA).read_text(encoding="utf-8")


# ---------------------------------------------------- quali IP passano


@pytest.mark.parametrize("indirizzo", [
    "8.8.8.8", "1.1.1.1", "203.0.113.10".replace("203.0.113.10", "9.9.9.9"),
    "2606:4700:4700::1111",
])
def test_indirizzi_pubblici_accettati(sync, indirizzo):
    assert sync.indirizzo_valido(indirizzo) is not None


@pytest.mark.parametrize("indirizzo", [
    "127.0.0.1", "::1", "192.168.1.10", "10.0.0.1", "172.16.5.5",
    "169.254.1.1", "224.0.0.1", "100.64.0.1",
    "203.0.113.10",   # rete di documentazione: non instradabile
    "::ffff:127.0.0.1",
    "ciao", "", "1.2.3.4 qualcosa", "999.999.999.999",
    "1.2.3.4; rm -rf /",   # niente di tutto cio' deve poter finire nel file
])
def test_indirizzi_da_non_scrivere_mai(sync, indirizzo):
    """Il file finisce dentro la configurazione di nginx: qui si ferma
    tutto cio' che non e' un indirizzo pubblico vero — indirizzi interni
    compresi, perche' bloccare la rete di casa vorrebbe dire mostrare la
    pagina di blocco a tutta la casa."""
    assert sync.indirizzo_valido(indirizzo) is None


def test_ip_rifiutato_non_arriva_nel_file(sync):
    """Un indirizzo rifiutato non cambia niente: non finisce nel file, e
    non fa nemmeno rigenerare o ricaricare nginx — non c'e' niente di
    nuovo da dire a nginx, e ricaricarlo per nulla sarebbe solo lavoro
    sprecato a ogni tentativo."""
    assert sync.blocca("photocarcifo-manuale", "127.0.0.1") == 0
    assert not Path(sync.USCITA).exists()
    assert sync._ricaricato == []
    assert "RIFIUTATO" in Path(sync.LOG).read_text(encoding="utf-8")

    # E con un file gia' esistente, quel file resta intatto.
    sync.blocca("photocarcifo-manuale", "8.8.8.8")
    prima = _contenuto(sync)
    sync.blocca("photocarcifo-manuale", "192.168.1.1")
    assert _contenuto(sync) == prima


# ------------------------------------------------------ blocca / libera


def test_blocca_scrive_la_riga_per_nginx(sync):
    assert sync.blocca("photocarcifo-manuale", "8.8.8.8") == 0
    assert "8.8.8.8 1;" in _contenuto(sync)
    assert sync._ricaricato, "nginx doveva essere ricaricato"


def test_libera_toglie_la_riga(sync):
    sync.blocca("photocarcifo-manuale", "8.8.8.8")
    assert sync.libera("photocarcifo-manuale", "8.8.8.8") == 0
    assert "8.8.8.8" not in _contenuto(sync)


def test_libera_indirizzo_mai_bloccato_non_e_un_errore(sync):
    """fail2ban puo' chiedere di liberare un indirizzo che qui non c'e'
    (ban applicato quando la sincronizzazione era rotta, per esempio): il
    risultato voluto — non bloccato — c'e' gia'."""
    assert sync.libera("photocarcifo-manuale", "8.8.8.8") == 0


def test_stesso_ip_in_due_jail_una_riga_sola(sync):
    sync.blocca("photocarcifo-login", "8.8.8.8")
    sync.blocca("nginx-botsearch", "8.8.8.8")
    assert _contenuto(sync).count("8.8.8.8 1;") == 1
    # e liberarlo da una sola jail non lo toglie dall'altra
    sync.libera("photocarcifo-login", "8.8.8.8")
    assert "8.8.8.8 1;" in _contenuto(sync)
    sync.libera("nginx-botsearch", "8.8.8.8")
    assert "8.8.8.8" not in _contenuto(sync)


def test_svuota_tocca_una_jail_sola(sync):
    """Quando una jail riparte, i suoi indirizzi vanno rifatti da zero —
    ma quelli delle altre jail non c'entrano niente e devono restare."""
    sync.blocca("photocarcifo-login", "8.8.8.8")
    sync.blocca("photocarcifo-manuale", "1.1.1.1")
    sync.svuota("photocarcifo-login")
    testo = _contenuto(sync)
    assert "8.8.8.8" not in testo
    assert "1.1.1.1 1;" in testo


def test_avvia_riparte_pulito(sync):
    """actionstart: fail2ban sta per riapplicare i ban ancora validi uno
    per uno, quelli scaduti mentre era spento devono sparire."""
    sync.blocca("photocarcifo-login", "8.8.8.8")
    sync.avvia_o_svuota = None  # solo per chiarezza: l'azione e' svuota()
    assert sync.svuota("photocarcifo-login") == 0
    assert "8.8.8.8" not in _contenuto(sync)


# ------------------------------------------------- non lasciare nginx rotto


def test_se_nginx_rifiuta_si_torna_indietro(sync):
    """Il punto piu' importante di tutto lo script: se la configurazione
    non va bene, il file torna esattamente com'era e non si ricarica
    niente. Meglio un ban che non compare che il sito giu' per tutti."""
    sync.blocca("photocarcifo-manuale", "8.8.8.8")
    prima = _contenuto(sync)
    sync._ricaricato.clear()

    sync._approva = False
    assert sync.blocca("photocarcifo-manuale", "1.1.1.1") == 1

    assert _contenuto(sync) == prima, "il file doveva tornare come prima"
    assert "1.1.1.1" not in _contenuto(sync)
    assert sync._ricaricato == [], "non si ricarica una configurazione rifiutata"
    assert "SINCRONIZZAZIONE FALLITA" in Path(sync.LOG).read_text(encoding="utf-8")


def test_se_nginx_rifiuta_al_primo_ban_non_resta_un_file_a_meta(sync):
    """Caso limite: nessun file precedente da ripristinare."""
    sync._approva = False
    assert sync.blocca("photocarcifo-manuale", "8.8.8.8") == 1
    assert not Path(sync.USCITA).exists()


def test_il_file_dichiara_di_essere_generato(sync):
    """Chi lo apre a mano deve capire subito che le sue modifiche
    verranno sovrascritte al primo ban."""
    sync.blocca("photocarcifo-manuale", "8.8.8.8")
    assert "non modificare a mano" in _contenuto(sync)


@pytest.mark.parametrize("nome", ["../../fuori", "..", ".", "a/../..", "", "/", "  "])
def test_nome_jail_pericoloso_resta_nella_cartella_di_stato(sync, nome):
    """Il nome della jail arriva da fail2ban e finisce in un percorso.

    Il test di prima guardava il posto sbagliato (dentro tmp_path invece
    che accanto a STATO) e sarebbe passato anche togliendo del tutto la
    protezione: se ne accorge la code review. Qui si controlla la cosa
    vera — la cartella usata sta SEMPRE dentro STATO — e si prova ".."
    che e' il caso che faceva danno davvero (svuota("..") cancellava lo
    storico dei ban in /var/lib/photocarcifo)."""
    from pathlib import Path as P
    cartella = P(sync._cartella_jail(nome)).resolve()
    stato = P(sync.STATO).resolve()
    assert cartella.parent == stato, f"{cartella} e' finita fuori da {stato}"
    assert cartella != stato


def test_svuota_una_jail_dal_nome_storto_non_cancella_lo_storico(sync, tmp_path):
    """La prova concreta del difetto: prima, svuota("..") faceva
    os.remove su ogni file di /var/lib/photocarcifo."""
    from pathlib import Path as P
    stato = P(sync.STATO)
    stato.mkdir(parents=True, exist_ok=True)
    prezioso = stato.parent / "ban-storico.json"
    prezioso.write_text("{}", encoding="utf-8")
    sync.svuota("..")
    assert prezioso.exists(), "lo storico dei ban non deve sparire mai"


# --------------------------------------------------- il giro di main()


@pytest.mark.parametrize("azione", ["avvia", "ferma", "svuota"])
def test_main_manda_avvia_ferma_e_svuota_sulla_stessa_strada(sync, monkeypatch, azione):
    """Su questo poggia tutto il ragionamento sui riavvii: all'avvio di
    una jail i suoi indirizzi vanno rifatti da zero, perche' fail2ban sta
    per riapplicare uno per uno quelli ancora validi. Se qualcuno
    togliesse "avvia" da quella riga, i ban scaduti tornerebbero a
    sopravvivere ai riavvii senza che nessun test se ne accorgesse."""
    sync.blocca("photocarcifo-login", "8.8.8.8")
    monkeypatch.setattr(sync.sys, "argv", ["x", azione, "photocarcifo-login"])
    assert sync.main() == 0
    assert "8.8.8.8" not in _contenuto(sync)


def test_main_azione_sconosciuta_e_argomenti_mancanti(sync, monkeypatch):
    monkeypatch.setattr(sync.sys, "argv", ["x", "balla"])
    assert sync.main() == 2
    monkeypatch.setattr(sync.sys, "argv", ["x"])
    assert sync.main() == 2


def test_main_blocca_e_libera_passando_dagli_argomenti(sync, monkeypatch):
    monkeypatch.setattr(sync.sys, "argv", ["x", "blocca", "photocarcifo-manuale", "8.8.8.8"])
    assert sync.main() == 0
    assert "8.8.8.8 1;" in _contenuto(sync)
    monkeypatch.setattr(sync.sys, "argv", ["x", "libera", "photocarcifo-manuale", "8.8.8.8"])
    assert sync.main() == 0
    assert "8.8.8.8" not in _contenuto(sync)


# ------------------------------------- riconvergenza dopo un fallimento


def test_dopo_un_blocco_fallito_il_successivo_rimette_tutto_a_posto(sync):
    """La proprieta' su cui si regge il disegno: un ban perso non e'
    permanente, la prima sincronizzazione riuscita riporta lo stato
    completo. Qui A fallisce, B riesce, e alla fine nginx deve avere
    entrambi... o meglio: A e' stato dimenticato apposta (vedi blocca()),
    quindi deve esserci solo B, che e' la cosa onesta — lo stato non
    promette un blocco che non c'e'."""
    sync._approva = False
    assert sync.blocca("photocarcifo-manuale", "8.8.8.8") == 1
    sync._approva = True
    assert sync.blocca("photocarcifo-manuale", "1.1.1.1") == 0
    testo = _contenuto(sync)
    assert "1.1.1.1 1;" in testo
    assert "8.8.8.8" not in testo, "un ban che non e' riuscito non deve tornare da solo"


def test_uno_sblocco_fallito_non_lascia_la_persona_bloccata_per_sempre(sync):
    """Il caso peggiore di tutti: fail2ban non richiama mai actionunban.
    Se lo stato dimenticasse l'indirizzo mentre nginx continua a
    bloccarlo, quella persona resterebbe sulla pagina di blocco per
    sempre. Lo stato deve restare com'era, cosi' il tentativo successivo
    lo toglie davvero."""
    sync.blocca("photocarcifo-manuale", "8.8.8.8")
    sync._approva = False
    assert sync.libera("photocarcifo-manuale", "8.8.8.8") == 1
    assert "8.8.8.8 1;" in _contenuto(sync)  # nginx lo blocca ancora

    sync._approva = True
    assert sync.libera("photocarcifo-manuale", "8.8.8.8") == 0
    assert "8.8.8.8" not in _contenuto(sync)


def test_se_la_ricarica_fallisce_lo_dice(sync):
    sync._reload_ok = False
    assert sync.blocca("photocarcifo-manuale", "8.8.8.8") == 1
    assert "RICARICA NGINX FALLITA" in Path(sync.LOG).read_text(encoding="utf-8")


def test_nginx_che_non_risponde_non_lascia_il_file_nuovo(sync, monkeypatch):
    """Se `nginx -t` va in timeout, il file convalidato di prima deve
    restare al suo posto: e' proprio il caso in cui non si sa se la
    configurazione nuova sia buona."""
    sync.blocca("photocarcifo-manuale", "8.8.8.8")
    prima = _contenuto(sync)

    def scoppia():
        raise sync.subprocess.TimeoutExpired(cmd="nginx -t", timeout=30)

    monkeypatch.setattr(sync, "nginx_approva", scoppia)
    with pytest.raises(sync.subprocess.TimeoutExpired):
        sync.blocca("photocarcifo-manuale", "1.1.1.1")
    assert _contenuto(sync) == prima, "il file doveva tornare quello convalidato"


def test_niente_ricarica_se_l_elenco_non_cambia(sync):
    """All'avvio di fail2ban ogni jail chiedeva una rigenerazione: erano
    quattro ricariche identiche di fila, e ogni ricarica lascia in vita i
    vecchi worker di nginx finche' non chiudono le connessioni."""
    sync.blocca("photocarcifo-manuale", "8.8.8.8")
    quante = len(sync._ricaricato)
    sync.svuota("nginx-limit-req")          # jail vuota: niente cambia
    sync.blocca("nginx-botsearch", "8.8.8.8")  # stesso IP da un'altra jail
    assert len(sync._ricaricato) == quante, "nginx ricaricato senza motivo"
