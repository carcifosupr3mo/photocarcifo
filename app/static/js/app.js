/* Photocarcifo - caricamento progressivo, visualizzatore, selezione multipla.

   La selezione sopravvive al cambio pagina: gli identificativi restano in
   sessionStorage, cosi' su un album da mille foto si possono scegliere
   immagini sparse su piu' pagine e scaricarle in un colpo solo.
*/
(function () {
  "use strict";

  var selecting = false, grid = null, items = [];
  var btnMode, btnDl, btnCancel, btnDel, btnShareSel, btnTutte;
  // Indirizzo gia' ottenuto per la selezione corrente: si riusa finche'
  // la selezione non cambia, altrimenti il pannello riaprirebbe il
  // collegamento di una scelta precedente. Azzerato da scriviSel/azzeraSel,
  // che sono l'unico passaggio da cui la selezione viene modificata.
  var shareCacheSel = {};
  var CHIAVE = "pc_sel_" + (document.body.getAttribute("data-node") || location.pathname);

  function leggiSel() {
    try {
      var v = sessionStorage.getItem(CHIAVE);
      return v ? JSON.parse(v) : [];
    } catch (e) { return []; }
  }
  function scriviSel(ids) {
    try { sessionStorage.setItem(CHIAVE, JSON.stringify(ids)); } catch (e) {}
    shareCacheSel = {};
  }
  function selIds() { return leggiSel(); }
  function isSel(id) { return leggiSel().indexOf(String(id)) !== -1; }
  function toggleId(id) {
    var ids = leggiSel(), i = ids.indexOf(String(id));
    if (i === -1) ids.push(String(id)); else ids.splice(i, 1);
    scriviSel(ids);
    return i === -1;
  }
  function azzeraSel() {
    try { sessionStorage.removeItem(CHIAVE); } catch (e) {}
    shareCacheSel = {};
  }

  function initLazyLoad() {
    // Le immagini che il server consegna gia' con il proprio indirizzo (la
    // prima di ogni album, per farla arrivare prima delle altre) non hanno
    // data-src e non passano di qui: gli si applica subito la versione ad
    // alta densita', che altrimenti non userebbero mai.
    Array.prototype.forEach.call(
      document.querySelectorAll("img[data-srcset]:not([data-src])"),
      function (img) {
        img.srcset = img.getAttribute("data-srcset");
        img.removeAttribute("data-srcset");
      });

    var imgs = document.querySelectorAll("img[data-src]");
    if (!("IntersectionObserver" in window)) {
      Array.prototype.forEach.call(imgs, loadImg);
      return;
    }
    var io = new IntersectionObserver(function (es, obs) {
      es.forEach(function (e) {
        if (e.isIntersecting) { loadImg(e.target); obs.unobserve(e.target); }
      });
    }, { rootMargin: "400px 0px", threshold: 0.01 });
    Array.prototype.forEach.call(imgs, function (img) { io.observe(img); });
  }

  function loadImg(img) {
    var src = img.getAttribute("data-src");
    if (!src) return;
    var set = img.getAttribute("data-srcset");
    if (set) { img.srcset = set; img.removeAttribute("data-srcset"); }
    // data-src si toglie a immagine arrivata, non prima: e' la sua assenza
    // che fa comparire la fotografia in dissolvenza. Va tolto anche in caso
    // di errore, altrimenti una miniatura che non si carica lascerebbe un
    // riquadro trasparente per sempre invece del testo alternativo.
    var svela = function () { img.removeAttribute("data-src"); };
    img.addEventListener("load", svela, { once: true });
    img.addEventListener("error", svela, { once: true });
    img.src = src;
    // Se era gia' in memoria, "load" puo' essere passato prima che ci
    // mettessimo in ascolto.
    if (img.complete) svela();
  }

  function refreshBar() {
    var n = selIds().length;
    if (btnDl) {
      btnDl.textContent = T("sel_scarica", {n: n});
      btnDl.disabled = n === 0;
      btnDl.style.opacity = n === 0 ? ".5" : "1";
    }
    if (btnShareSel) {
      btnShareSel.textContent = T("sel_condividi", {n: n});
      btnShareSel.disabled = n === 0;
      btnShareSel.style.opacity = n === 0 ? ".5" : "1";
    }
    if (btnDel) {
      btnDel.textContent = n ? T("sel_rimuovi_n", {n: n}) : T("sel_rimuovi");
      btnDel.disabled = n === 0;
      btnDel.style.opacity = n === 0 ? ".5" : "1";
    }
    var eco = document.getElementById("selEcho");
    if (eco) {
      eco.textContent = n ? T("sel_eco", {n: n}) : "";
      eco.style.display = n ? "block" : "none";
    }
  }

  function segna(item, attivo) {
    item.classList.toggle("selected", attivo);
    var box = item.querySelector(".sel-box");
    if (box) box.setAttribute("aria-checked", attivo ? "true" : "false");
  }

  function toggle(item) {
    var id = item.getAttribute("data-id");
    if (!id) return;
    segna(item, toggleId(id));
    refreshBar();
  }

  /* Prende o lascia tutte le fotografie di questa pagina. Non tutto
     l'album: le pagine sono da centoventi e per l'album intero c'e' gia'
     "Scarica tutto". Se ne manca anche una sola le prende tutte, altrimenti
     le lascia: un solo bottone per i due gesti, senza doverne leggere due. */
  function tutteQuestaPagina() {
    // Una lettura sola e una scrittura sola: passando per toggleId si
    // rileggerebbe e riscriverebbe la memoria di sessione centoventi
    // volte di fila, una per fotografia, per arrivare allo stesso elenco.
    var ids = leggiSel();
    var dentro = {};
    ids.forEach(function (id) { dentro[id] = true; });
    var manca = items.some(function (it) {
      var id = it.getAttribute("data-id");
      return id && !dentro[id];
    });
    items.forEach(function (it) {
      var id = it.getAttribute("data-id");
      if (!id) return;
      if (manca && !dentro[id]) { ids.push(String(id)); dentro[id] = true; }
      else if (!manca && dentro[id]) { delete dentro[id]; }
      segna(it, manca);
    });
    if (!manca) {
      ids = ids.filter(function (id) { return dentro[id]; });
    }
    scriviSel(ids);
    refreshBar();
  }

  /* Scaricamento di molte fotografie insieme.

     L'archivio si prepara mentre viene mandato: il server non sa dire
     quanto pesera', quindi una percentuale sarebbe inventata e qui non se
     ne mostra nessuna. Si mostrano invece i due momenti veri: "sto
     preparando" e "e' partito". Il secondo lo dice il server stesso,
     scrivendo un biscottino non appena la risposta comincia (non quando
     il primo file e' davvero pronto: e' solo il segnale che il server ha
     preso in carico la richiesta); la pagina lo controlla e toglie
     l'avviso.

     Il bottone si sblocca dopo mezzo minuto anche se l'archivio non e'
     ancora partito, per non lasciare la pagina inservibile se qualcosa va
     storto per strada — ma sbloccare il bottone non deve voler dire "si
     puo' richiedere di nuovo lo stesso pacco": ARCHIVI_IN_CORSO tiene
     traccia, per indirizzo, di quali scaricamenti sono ancora aperti, a
     prescindere da quale bottone li ha avviati o da quanti minuti sono
     passati. La voce si toglie solo quando il biscottino conferma che
     l'archivio e' arrivato, oppure dopo un tempo lungo (il download piu'
     lento visto fin qui e' su 2000 foto, meno di un minuto: tre sono un
     margine ampio) che fa da rete di sicurezza se il segnale si perde per
     strada — un client che chiude la scheda a meta', o un proxy che
     inghiotte il cookie. */
  var ARCHIVI_IN_CORSO = {};
  var ARCHIVIO_MARGINE_MS = 180000;

  /* Il download partiva da un iframe invisibile (iframe.src = indirizzo),
     per evitare che un 409 (risposta JSON senza attachment) navigasse via
     dalla pagina mostrando il JSON al posto suo. Funzionava su Chrome, ma
     Safari e le webview che ne condividono il motore (Instagram, Facebook,
     sempre WebKit su iOS) non trattano come download una risposta arrivata
     dentro un iframe: il file non si salva mai, anche se e' arrivato per
     intero e il biscottino di conferma e' scattato.

     Il rimedio, un <a download> vero cliccato da codice, basta su Android
     anche dentro Instagram: quella webview non sa salvare file, ma il
     sistema operativo se ne accorge da solo e offre di aprire Chrome, che
     il file lo salva per davvero (verificato: lo zip arriva intero).

     Su iOS non basta. Registrazione dello schermo alla mano: dentro
     Instagram il tocco su "Scarica" fa comparire il nostro "Scaricamento
     avviato" (il biscottino di conferma arriva regolarmente: il server ha
     mandato tutto), ma li' si ferma tutto — nessun salvataggio, nessuna
     Safari che si apre da sola. A differenza di Android, iOS non offre a
     una app un modo automatico di passare un download a un browser vero:
     e' Apple stessa a non prevederlo, quindi nessun trucco lato pagina puo'
     bypassarlo dall'interno della webview.

     La via che invece funziona e' il pannello di condivisione di iOS
     (navigator.share con dei file): e' un'API web standard, non un tentativo
     di scappare dall'app, e Instagram non ha motivo di bloccarla visto che
     la usa anche lei. Il file si scarica in memoria e si passa al pannello,
     dove "Salva in File" (o "Salva immagine") salva per davvero. Serve pero'
     rispettare due vincoli di WebKit, ed e' per questo che il percorso ha
     due tocchi invece di uno:

     - navigator.share() vuole un gesto recente della persona, e la finestra
       dura pochi secondi: dopo un fetch di decine di megabyte sarebbe gia'
       scaduta. Quindi il primo tocco scarica e basta, il secondo (sul
       bottone "Salva") apre il pannello dentro il proprio gesto.
     - tenere l'archivio in memoria non e' gratis: oltre un certo peso non
       vale la pena rischiare che la webview venga uccisa a meta' strada, e
       si passa direttamente alle istruzioni per Safari.

     Tutto questo vale solo per le webview: Safari vero, Chrome/Firefox per
     iOS, Android e desktop continuano a passare dal percorso di sempre. */

  // Oltre questi limiti si rinuncia a tenere l'archivio in memoria: meglio
  // mandare la persona in Safari subito che scaricare cento megabyte di
  // dati mobili per poi far morire la scheda. Il tetto e' sui byte
  // scaricati, ma il picco vero e' quasi il doppio: nell'istante in cui si
  // costruisce il Blob convivono i pezzi e la loro copia.
  var TETTO_MEMORIA = 100 * 1024 * 1024;
  var TETTO_FOTO = 30;

  function suIos() {
    var ua = navigator.userAgent;
    // Da iPadOS 13 un iPad si presenta come "Macintosh": lo tradisce lo
    // schermo tattile, che nessun Mac ha.
    return /iPhone|iPad|iPod/.test(ua) ||
      (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
  }

  function browserProprio(ua) {
    // Safari vero mette sempre "Version/x.y". Chrome, Firefox, Edge e Opera
    // per iOS sotto sono WebKit come tutti, ma hanno una propria gestione
    // dei download e si riconoscono dalla loro sigla.
    return /Version\/|CriOS|FxiOS|EdgiOS|OPiOS/.test(ua);
  }

  function webviewLimitata() {
    // Solo iOS: su Android la webview di Instagram non sa salvare file, ma
    // il sistema operativo offre da solo di aprire Chrome, e il download
    // arriva. Non c'e' niente da correggere li'.
    return suIos() && !browserProprio(navigator.userAgent);
  }

  function appOspite() {
    // Serve solo a scrivere "Instagram" invece di "questa app" nel
    // messaggio: se non si riconosce, il testo generico va benissimo.
    var ua = navigator.userAgent;
    if (/Instagram/.test(ua)) return "Instagram";
    if (/FBAN|FBAV|FB_IAB/.test(ua)) return "Facebook";
    if (/Threads/.test(ua)) return "Threads";
    if (/TikTok|BytedanceWebview/.test(ua)) return "TikTok";
    if (/Snapchat/.test(ua)) return "Snapchat";
    if (/LinkedInApp/.test(ua)) return "LinkedIn";
    return "";
  }

  function apriInSafari(indirizzo) {
    // "x-safari-https://..." e' un indirizzo speciale che iOS riconosce da
    // qualunque app e dovrebbe aprire nel vero Safari. Si tenta comunque
    // (costa niente), ma non e' su questo che si conta: verificato che
    // dentro Instagram non parte quasi mai, perche' Instagram intercetta di
    // proposito i tentativi di uscire verso un'altra app. Per questo il
    // messaggio accanto al bottone spiega anche la strada a mano.
    var assoluto = new URL(indirizzo, location.href).href;
    location.href = assoluto.replace(/^https?:\/\//, "x-safari-$&");
  }

  function nomeDaRisposta(risposta, ripiego) {
    var cd = risposta.headers.get("Content-Disposition") || "";
    var m = /filename\*=UTF-8''([^;]+)/.exec(cd);
    if (m) {
      try { return decodeURIComponent(m[1]); } catch (e) { /* nome grezzo */ }
    }
    m = /filename="?([^";]+)"?/.exec(cd);
    return m ? m[1] : ripiego;
  }

  /* Scarica in memoria fermandosi se supera il tetto, invece di scoprire
     troppo tardi che l'archivio non ci sta. Chiama avanza(byte) mentre
     procede, cosi' chi guarda vede che qualcosa sta succedendo. */
  function scaricaConTetto(indirizzo, tetto, avanza, segnale) {
    return fetch(indirizzo, {
      credentials: "same-origin", signal: segnale
    }).then(function (r) {
      if (!r.ok) throw new Error("http " + r.status);
      var nome = nomeDaRisposta(r, "foto.zip");
      var tipo = r.headers.get("Content-Type") || "application/octet-stream";
      if (!r.body || !r.body.getReader) {
        // Browser senza stream: si prende tutto insieme, senza poter
        // fermare a meta'. Il tetto lo si controlla comunque dopo.
        return r.blob().then(function (b) {
          if (b.size > tetto) throw new Error("troppo-grande");
          return { blob: b, nome: nome };
        });
      }
      var lettore = r.body.getReader();
      var pezzi = [], totale = 0;
      return (function leggi() {
        return lettore.read().then(function (esito) {
          if (esito.done) {
            var insieme = new Blob(pezzi, { type: tipo });
            // I pezzi sono stati copiati dentro il Blob: tenerli ancora
            // raddoppierebbe la memoria occupata fino al prossimo giro di
            // pulizia, proprio quando ce n'e' di meno.
            pezzi.length = 0;
            return { blob: insieme, nome: nome };
          }
          totale += esito.value.byteLength;
          if (totale > tetto) {
            lettore.cancel().catch(function () { /* si stava gia' mollando */ });
            throw new Error("troppo-grande");
          }
          pezzi.push(esito.value);
          if (avanza) avanza(totale);
          return leggi();
        });
      })();
    });
  }

  /* Apre il pannello di condivisione. Va chiamata dentro il gesto della
     persona, non dopo un'attesa. Restituisce "condiviso", "annullato" (ha
     chiuso il pannello: sua scelta, non un errore) o "non-supportato". */
  function condividiFile(blob, nome) {
    if (!(window.navigator && navigator.share && navigator.canShare &&
          window.File)) {
      return Promise.resolve("non-supportato");
    }
    var file;
    try {
      file = new File([blob], nome,
        { type: blob.type || "application/octet-stream" });
    } catch (e) {
      return Promise.resolve("non-supportato");
    }
    var puo = false;
    try { puo = navigator.canShare({ files: [file] }); } catch (e) { puo = false; }
    if (!puo) return Promise.resolve("non-supportato");
    return navigator.share({ files: [file] })
      .then(function () { return "condiviso"; })
      .catch(function (e) {
        return (e && e.name === "AbortError") ? "annullato" : "non-supportato";
      });
  }

  /* Il riquadro che accompagna il download dentro una webview. Ha tre
     momenti — sto scaricando, e' pronto da salvare, non si puo' fare qui —
     e si chiude sempre: non intrappola nessuno dentro una pagina bloccata. */
  function riquadroScarico() {
    var fondo = document.createElement("div");
    fondo.className = "iosdl-fondo";
    var scatola = document.createElement("div");
    scatola.className = "iosdl";
    scatola.setAttribute("role", "dialog");
    scatola.setAttribute("aria-modal", "true");
    var titolo = document.createElement("h2");
    titolo.className = "iosdl-titolo";
    titolo.id = "iosdl-titolo";
    scatola.setAttribute("aria-labelledby", titolo.id);
    var testo = document.createElement("p");
    testo.className = "iosdl-testo";
    // Lo stesso paragrafo racconta l'attesa e poi il risultato: senza
    // questo, per un lettore di schermo il riquadro resterebbe muto per
    // tutto lo scaricamento.
    testo.setAttribute("role", "status");
    testo.setAttribute("aria-live", "polite");
    var azioni = document.createElement("div");
    azioni.className = "iosdl-azioni";
    scatola.appendChild(titolo);
    scatola.appendChild(testo);
    scatola.appendChild(azioni);
    fondo.appendChild(scatola);

    var attivoPrima = document.activeElement;
    // Chi apre il riquadro puo' chiedere di essere avvisato quando si
    // chiude, comunque lo si chiuda: dal bottone, con Esc o toccando fuori.
    // Serve a fermare lo scaricamento in corso, non solo a togliere il
    // riquadro dallo schermo.
    var allaChiusura = null;
    function chiudi() {
      if (!fondo.parentNode) return;
      document.removeEventListener("keydown", tasto);
      fondo.parentNode.removeChild(fondo);
      document.body.classList.remove("iosdl-aperto");
      if (attivoPrima && attivoPrima.focus) attivoPrima.focus();
      var avvisa = allaChiusura;
      allaChiusura = null;   // mai due volte, nemmeno se rinuncia() richiama chiudi()
      if (avvisa) avvisa();
    }
    function tasto(e) {
      if (e.key !== "Escape") return;
      // Il visualizzatore ascolta anch'esso Esc, e da sotto: senza
      // fermare qui la propagazione un solo tasto chiuderebbe riquadro e
      // fotografia insieme, lasciando il fuoco nel vuoto.
      e.preventDefault();
      e.stopImmediatePropagation();
      chiudi();
    }
    // Il fondo si chiude toccandolo fuori dal riquadro: chi non capisce
    // cosa gli si sta chiedendo deve poter tornare alla pagina in un tocco.
    fondo.addEventListener("click", function (e) {
      if (e.target === fondo) chiudi();
    });
    document.addEventListener("keydown", tasto);
    document.body.classList.add("iosdl-aperto");
    document.body.appendChild(fondo);

    function bottone(etichetta, classe, azione) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "btn " + classe;
      b.textContent = etichetta;
      b.addEventListener("click", azione);
      azioni.appendChild(b);
      return b;
    }
    function svuota() {
      while (azioni.firstChild) azioni.removeChild(azioni.firstChild);
    }
    return {
      chiudi: chiudi,
      allaChiusura: function (f) { allaChiusura = f; },
      titolo: function (t) { titolo.textContent = t; },
      testo: function (t) { testo.textContent = t; },
      azioni: function () { svuota(); return { bottone: bottone }; },
      metteAFuoco: function (elemento) {
        if (elemento && elemento.focus) elemento.focus();
      }
    };
  }

  /* La strada per chi non puo' scaricare da qui: si prova comunque ad
     aprire Safari, e intanto si spiega come farlo a mano, perche' il
     tentativo automatico Instagram lo blocca quasi sempre. */
  function riquadroIstruzioni(riquadro, testoSpiegazione) {
    var app = appOspite();
    // Si manda a Safari la pagina, non l'indirizzo del file: l'archivio
    // di un album riservato dipende dai biscottini di questa sessione, che
    // Safari non ha: aprendolo di la' si otterrebbe un rifiuto. Ed e' anche
    // quello che dice il messaggio ("apri questa pagina in Safari").
    var pagina = location.href;
    var a = riquadro.azioni();
    riquadro.titolo(app ? T("ios_titolo_app", { app: app }) : T("ios_titolo"));
    riquadro.testo(testoSpiegazione);
    var primo = a.bottone(T("ios_apri_safari"), "btn-accent", function () {
      apriInSafari(pagina);
    });
    a.bottone(T("ios_copia"), "btn-ghost", function (e) {
      var bottone = e.currentTarget;
      var riuscito = function () { bottone.textContent = T("ios_copiato"); };
      // Se copiare non riesce si mostra l'indirizzo perche' si possa
      // prendere a mano — ma dentro il riquadro, non in un avviso: gli
      // avvisi stanno sotto il velo, dove non si selezionano nemmeno.
      var aMano = function () { riquadro.testo(pagina); };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(pagina).then(riuscito, aMano);
      } else {
        aMano();
      }
    });
    a.bottone(T("ios_annulla"), "btn-ghost", riquadro.chiudi);
    riquadro.metteAFuoco(primo);
  }

  /* Il percorso completo dentro una webview di iOS. Restituisce sempre
     qualcosa di comprensibile: le foto salvate, oppure la strada per
     salvarle altrove. */
  function percorsoWebview(indirizzo, quante) {
    // Un secondo tocco mentre il riquadro e' gia' aperto ne aprirebbe un
    // altro sopra, e farebbe scaricare due volte lo stesso archivio.
    if (document.querySelector(".iosdl-fondo")) return;
    var riquadro = riquadroScarico();
    if (quante && quante > TETTO_FOTO) {
      riquadroIstruzioni(riquadro,
        T("ios_troppe", { n: quante, max: TETTO_FOTO }));
      return;
    }
    riquadro.titolo(T("ios_titolo_preparo"));
    riquadro.testo(T("ios_preparo"));
    var annulla = false;
    // Chiudere il riquadro deve fermare davvero il traffico: senza questo,
    // chi rinuncia dopo due secondi continuerebbe a scaricare in silenzio
    // decine di megabyte di dati mobili.
    var freno = window.AbortController ? new AbortController() : null;
    function rinuncia() {
      annulla = true;
      if (freno) freno.abort();
      riquadro.chiudi();
    }
    riquadro.allaChiusura(rinuncia);
    var a = riquadro.azioni();
    // Il fuoco entra nel riquadro fin dall'attesa: aprire un dialogo e
    // lasciare il fuoco dietro significa, per chi usa un lettore di
    // schermo, non sentire niente e non trovare nemmeno l'unico "Annulla".
    riquadro.metteAFuoco(a.bottone(T("ios_annulla"), "btn-ghost", rinuncia));
    scaricaConTetto(indirizzo, TETTO_MEMORIA, function (byte) {
      if (!annulla) {
        riquadro.testo(T("ios_avanzamento",
          { mb: Math.round(byte / 1048576) }));
      }
    }, freno ? freno.signal : undefined).then(function (o) {
      if (annulla) return;
      riquadro.titolo(T("ios_titolo_pronto"));
      riquadro.testo(T("ios_pronto"));
      var b = riquadro.azioni();
      var salva = b.bottone(T("ios_salva"), "btn-accent", function () {
        // Un secondo tocco mentre il pannello e' gia' aperto: WebKit
        // rifiuta la seconda condivisione, e senza questo blocco il
        // rifiuto verrebbe scambiato per "questo browser non sa salvare"
        // — le istruzioni di ripiego comparirebbero mentre il pannello
        // sta funzionando benissimo davanti agli occhi di chi salva.
        if (salva.disabled) return;
        salva.disabled = true;
        // Dentro il gesto: e' l'unico momento in cui WebKit lascia
        // aprire il pannello di condivisione.
        condividiFile(o.blob, o.nome).then(function (esito) {
          salva.disabled = false;
          // Il riquadro puo' essere stato chiuso nel frattempo (tocco
          // fuori, Esc): riscriverlo ora vorrebbe dire parlare a un
          // pezzo di pagina che non e' piu' attaccato a niente.
          if (annulla) return;
          if (esito === "condiviso") {
            riquadro.chiudi();
            PC.avviso(T("ios_salvato"), "ok");
          } else if (esito === "non-supportato") {
            riquadroIstruzioni(riquadro, T("ios_testo"));
          }
          // "annullato": ha chiuso il pannello, il riquadro resta com'e'
          // cosi' puo' riprovare senza riscaricare niente.
        });
      });
      b.bottone(T("ios_annulla"), "btn-ghost", riquadro.chiudi);
      riquadro.metteAFuoco(salva);
    }, function (errore) {
      if (annulla) return;
      var messaggio = (errore && errore.message === "troppo-grande")
        ? T("ios_troppo_grande") : T("ios_testo");
      riquadroIstruzioni(riquadro, messaggio);
    });
  }

  function scaricaVero(indirizzo) {
    // Chi chiama si e' gia' tolto di mezzo il caso iOS-dentro-una-webview
    // (avviaZip, sotto): qui arriva solo chi un vero download lo sa fare
    // davvero. L'attributo download forza il browser a salvare la
    // risposta qualunque sia il suo contenuto (stesso dominio), quindi
    // copre anche il caso 409: si salva un piccolo file invece di
    // navigare via, la pagina resta quella di prima e il biscottino
    // racconta comunque cos'e' successo.
    var a = document.createElement("a");
    a.href = indirizzo;
    a.download = "";
    a.style.display = "none";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  function avviaZip(indirizzo, bottone, quante) {
    if (bottone && bottone.disabled) return;
    if (webviewLimitata()) {
      // Tutto il resto della funzione gira intorno al biscottino "e'
      // arrivato l'archivio": qui non serve a niente, perche' il
      // salvataggio avverra' nel pannello di condivisione, che la pagina
      // non puo' osservare con un biscottino.
      percorsoWebview(indirizzo, quante);
      return;
    }
    var partito = ARCHIVI_IN_CORSO[indirizzo];
    // "partito !== undefined" e non "partito": zero e' un istante valido
    // (Date.now() nel test lo restituisce davvero), il controllo deve
    // chiedere se la voce c'e', non se il numero e' diverso da zero.
    if (partito !== undefined && Date.now() - partito < ARCHIVIO_MARGINE_MS) {
      // Lo stesso pacco e' gia' in viaggio: non se ne chiede un secondo,
      // si spiega perche' il bottone sembra non rispondere.
      PC.avviso(T("zip_in_corso"));
      return;
    }
    ARCHIVI_IN_CORSO[indirizzo] = Date.now();
    var segno = String(Date.now());
    scriviBiscotto("pc_zip", "");
    if (bottone) {
      bottone.disabled = true;
      bottone.classList.add("in-attesa");
    }
    var avviso = PC.attesa ? PC.attesa(T("zip_preparo")) : null;
    var finito = false;
    function chiudi(messaggio, tipo) {
      if (finito) return;
      finito = true;
      if (avviso && avviso.chiudi) avviso.chiudi();
      if (bottone) {
        bottone.disabled = false;
        bottone.classList.remove("in-attesa");
      }
      if (messaggio) PC.avviso(messaggio, tipo);
    }
    var spia = setInterval(function () {
      var visto = leggiBiscotto("pc_zip");
      if (visto === segno) {
        clearInterval(spia);
        scriviBiscotto("pc_zip", "");
        delete ARCHIVI_IN_CORSO[indirizzo];
        chiudi(T("zip_pronto"), "ok");
      } else if (visto === "occupato:" + segno) {
        // Un altro processo tiene gia' lo stesso archivio: e' la stessa
        // situazione che ARCHIVI_IN_CORSO cerca di prevenire da solo
        // (senza sempre riuscirci: due schede, un refresh, un altro
        // dispositivo), qui confermata dal server. Nessun nuovo tentativo
        // automatico, si spiega e basta.
        clearInterval(spia);
        scriviBiscotto("pc_zip", "");
        delete ARCHIVI_IN_CORSO[indirizzo];
        chiudi(T("zip_in_corso"));
      }
    }, 400);
    setTimeout(function () {
      // Solo il bottone si sblocca: ARCHIVI_IN_CORSO resta finche' non
      // arriva il biscottino o non scade il margine piu' lungo sopra.
      clearInterval(spia);
      chiudi();
    }, 30000);
    scaricaVero(indirizzo + "&segnale=" + segno);
  }

  function leggiBiscotto(nome) {
    var parti = ("; " + document.cookie).split("; " + nome + "=");
    return parti.length === 2 ? parti.pop().split(";").shift() : "";
  }

  function scriviBiscotto(nome, valore) {
    // secure: il sito e' solo HTTPS, come tutti gli altri biscottini che
    // scrive (vedi cookie-avviso.js). Lo si toglie con max-age=0 non
    // appena serve, non resta piu' del tempo per cui e' stato pensato.
    document.cookie = nome + "=" + valore + ";path=/;max-age=" +
      (valore ? 60 : 0) + ";samesite=lax;secure";
  }

  function enterSelect() {
    selecting = true;
    document.body.classList.add("selecting");
    btnMode.style.display = "none";
    if (btnDl) btnDl.style.display = "inline-flex";
    if (btnDel) btnDel.style.display = "inline-flex";
    if (btnShareSel) btnShareSel.style.display = "inline-flex";
    if (btnTutte) btnTutte.style.display = "inline-flex";
    btnCancel.style.display = "inline-flex";
    refreshBar();
  }

  function exitSelect() {
    selecting = false;
    azzeraSel();
    document.body.classList.remove("selecting");
    items.forEach(function (it) { segna(it, false); });
    btnMode.style.display = "inline-flex";
    if (btnDl) btnDl.style.display = "none";
    if (btnDel) btnDel.style.display = "none";
    if (btnShareSel) btnShareSel.style.display = "none";
    if (btnTutte) btnTutte.style.display = "none";
    btnCancel.style.display = "none";
    refreshBar();
  }

  function initGrid() {
    grid = document.querySelector(".photo-grid");
    if (!grid) return;
    items = Array.prototype.slice.call(grid.querySelectorAll(".photo"));
    if (!items.length) return;

    btnMode = document.getElementById("selMode");
    btnDl = document.getElementById("dlSel");
    btnShareSel = document.getElementById("shareSel");
    btnTutte = document.getElementById("selTutte");
    btnCancel = document.getElementById("selCancel");
    btnDel = document.getElementById("delSel");

    items.forEach(function (it) {
      var id = it.getAttribute("data-id");
      if (!id) return;
      var box = document.createElement("span");
      box.className = "sel-box";
      box.setAttribute("role", "checkbox");
      box.setAttribute("aria-checked", "false");
      box.setAttribute("aria-label", T("sel_questa"));
      box.addEventListener("click", function (e) {
        e.preventDefault(); e.stopPropagation();
        if (!selecting) enterSelect();
        toggle(it);
      });
      it.appendChild(box);
      if (isSel(id)) segna(it, true);

      // Bottone di condivisione pubblico: visibile su ogni miniatura, per
      // ogni visitatore (non solo l'amministratore) e su ogni dimensione
      // schermo, telefono compreso — a differenza del gemello del
      // visualizzatore (.lb-share-top), che e' solo desktop. Chiama
      // /condividi/{id}, che e' pubblica: nessun campo #csrf da leggere.
      var shareBox = document.createElement("button");
      shareBox.type = "button";
      shareBox.className = "share-box";
      shareBox.setAttribute("aria-label", T("condividi_foto"));
      var shareCacheGrid = {};
      shareBox.addEventListener("click", function (e) {
        e.preventDefault(); e.stopPropagation();
        var img = it.querySelector("img");
        var anteprima = { src: img ? img.src : "", alt: it.getAttribute("data-alt") || "" };
        apriPannelloCondivisione("/condividi/" + id, null, shareBox, anteprima, shareCacheGrid);
      });
      it.appendChild(shareBox);
    });

    if (selIds().length && btnMode) enterSelect();

    if (btnMode && btnCancel) {
      btnMode.addEventListener("click", function (e) { e.preventDefault(); enterSelect(); });
      btnCancel.addEventListener("click", function (e) { e.preventDefault(); exitSelect(); });
      if (btnDl) btnDl.addEventListener("click", function (e) {
        e.preventDefault();
        var ids = selIds();
        if (!ids.length) return;
        avviaZip("/zip/select?ids=" + ids.join(","), btnDl, ids.length);
      });
      // "Scarica tutto l'album": e' il pacco piu' pesante di tutti, quello
      // per cui l'attesa si fa sentire davvero. Il numero di fotografie sta
      // in data-quante: dentro una webview di iOS decide se conviene
      // tenerle in memoria o mandare la persona in Safari.
      var btnTutto = document.getElementById("dlTutto");
      if (btnTutto) btnTutto.addEventListener("click", function (e) {
        e.preventDefault();
        avviaZip(btnTutto.getAttribute("href") + "?", btnTutto,
                 parseInt(btnTutto.getAttribute("data-quante"), 10) || 0);
      });
      if (btnTutte) btnTutte.addEventListener("click", function (e) {
        e.preventDefault(); tutteQuestaPagina();
      });
      if (btnDel) btnDel.addEventListener("click", function (e) {
        e.preventDefault(); rimuovi(selIds());
      });
      if (btnShareSel) btnShareSel.addEventListener("click", function (e) {
        e.preventDefault();
        var ids = selIds();
        if (!ids.length) return;
        apriPannelloCondivisione("/condividi/selezione", null, btnShareSel, null,
          shareCacheSel, null, { ids: ids.join(",") });
      });
      refreshBar();
    }

    initLightbox();
  }

  function rimuovi(ids) {
    if (!ids.length) return;
    var campo = document.getElementById("csrf");
    if (!campo) { PC.avviso(T("sessione")); return; }
    var testo = ids.length === 1 ? T("cestino_una")
              : T("cestino_n", {n: ids.length});
    if (!confirm(testo + "\n\n" + T("cestino_nota"))) return;
    btnDel.disabled = true; btnDel.textContent = T("rimozione");
    var fd = new FormData();
    fd.append("csrf_token", campo.value);
    fd.append("ids", ids.join(","));
    fetch("/admin/trash/media", { method: "POST", body: fd })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d && d.ok) { azzeraSel(); location.reload(); }
        else { PC.avviso(T("rimozione_ko")); btnDel.disabled = false; }
      })
      .catch(function () { PC.avviso(T("rimozione_ko")); btnDel.disabled = false; });
  }

  /* Pannello di condivisione stile YouTube (anteprima, link da copiare,
     bottoni social): UNICO per tutta la pagina, costruito una sola volta e
     appeso a document.body, cosi' lo possono richiamare sia i bottoni del
     visualizzatore sia i bottoni della griglia, entrambi pubblici e
     entrambi via /condividi/{id}. Prima viveva dentro
     initLightbox()/build(), pensato solo per il visualizzatore. */
  var sp = null;
  var spShareBtnAttivo = null;

  function buildSharePanel() {
    var panel = document.createElement("div");
    panel.className = "share-panel";
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-modal", "true");
    panel.setAttribute("aria-label", T("condividi_titolo"));
    panel.setAttribute("aria-hidden", "true");
    var panelCard = document.createElement("div");
    panelCard.className = "share-panel-card";

    var panelHead = document.createElement("div");
    panelHead.className = "share-panel-head";
    var panelTitolo = document.createElement("strong");
    panelTitolo.textContent = T("condividi_titolo");
    var panelCloseBtn = mk("button", "share-panel-close", "&times;", T("condividi_chiudi"));
    panelHead.appendChild(panelTitolo);
    panelHead.appendChild(panelCloseBtn);

    var panelPreview = document.createElement("div");
    panelPreview.className = "share-panel-preview";
    var panelImg = document.createElement("img");
    panelImg.alt = T("condividi_anteprima");
    var panelTesto = document.createElement("span");
    panelPreview.appendChild(panelImg);
    panelPreview.appendChild(panelTesto);

    var panelLinkRow = document.createElement("div");
    panelLinkRow.className = "share-panel-link";
    var panelLinkInput = document.createElement("input");
    panelLinkInput.type = "text";
    panelLinkInput.readOnly = true;
    panelLinkInput.setAttribute("aria-label", T("condividi_link"));
    var panelCopyBtn = mk("button", "btn btn-accent", "", T("condividi_copia"));
    panelCopyBtn.textContent = T("condividi_copia");
    panelLinkRow.appendChild(panelLinkInput);
    panelLinkRow.appendChild(panelCopyBtn);

    var panelSocial = document.createElement("div");
    panelSocial.className = "share-panel-social";
    var panelWa = document.createElement("a");
    panelWa.className = "btn btn-ghost";
    panelWa.target = "_blank";
    panelWa.rel = "noopener";
    panelWa.textContent = T("condividi_whatsapp");
    var panelTg = document.createElement("a");
    panelTg.className = "btn btn-ghost";
    panelTg.target = "_blank";
    panelTg.rel = "noopener";
    panelTg.textContent = T("condividi_telegram");
    var panelMail = document.createElement("a");
    panelMail.className = "btn btn-ghost";
    panelMail.textContent = T("condividi_email");
    // Condivisione di sistema: sul telefono apre l'elenco vero delle
    // applicazioni (messaggi, foto, note, AirDrop), non solo le tre che
    // sappiamo elencare noi. Esiste solo dove il browser la offre: dove
    // non c'e', restano WhatsApp, Telegram e posta come prima.
    var panelNativo = null;
    if (navigator.share) {
      panelNativo = document.createElement("button");
      panelNativo.type = "button";
      panelNativo.className = "btn btn-accent";
      panelNativo.textContent = T("condividi_altro");
      panelSocial.appendChild(panelNativo);
    }
    panelSocial.appendChild(panelWa);
    panelSocial.appendChild(panelTg);
    panelSocial.appendChild(panelMail);

    panelCard.appendChild(panelHead);
    panelCard.appendChild(panelPreview);
    panelCard.appendChild(panelLinkRow);
    panelCard.appendChild(panelSocial);
    panel.appendChild(panelCard);
    document.body.appendChild(panel);

    var p = { root: panel, backdrop: panel, card: panelCard,
              img: panelImg, testo: panelTesto,
              linkInput: panelLinkInput, copyBtn: panelCopyBtn,
              wa: panelWa, tg: panelTg, mail: panelMail, nativo: panelNativo,
              closeBtn: panelCloseBtn };

    panelCloseBtn.addEventListener("click", chiudiPannelloCondivisione);
    panel.addEventListener("click", function (e) {
      if (e.target === panel) chiudiPannelloCondivisione();
    });
    // Il tocco dentro la scheda non deve chiudere il pannello.
    panelCard.addEventListener("click", function (e) { e.stopPropagation(); });
    panelCopyBtn.addEventListener("click", function () {
      var url = panelLinkInput.value;
      var testoOriginale = panelCopyBtn.textContent;
      function fatto() {
        panelCopyBtn.textContent = T("condividi_fatto");
        setTimeout(function () { panelCopyBtn.textContent = testoOriginale; }, 1500);
      }
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(url).then(fatto).catch(function () {
          window.prompt(T("condividi_link"), url);
        });
      } else {
        window.prompt(T("condividi_link"), url);
      }
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && panel.classList.contains("open")) chiudiPannelloCondivisione();
    });

    return p;
  }

  function mostraPannelloCondivisione(url, bottone, anteprima) {
    if (!sp) sp = buildSharePanel();
    sp.img.src = (anteprima && anteprima.src) || "";
    sp.testo.textContent = (anteprima && anteprima.alt) || "";
    sp.linkInput.value = url;
    sp.wa.href = "https://wa.me/?text=" + encodeURIComponent(url);
    sp.tg.href = "https://t.me/share/url?url=" + encodeURIComponent(url);
    sp.mail.href = "mailto:?subject=" + encodeURIComponent(T("condividi_foto")) +
      "&body=" + encodeURIComponent(url);
    if (sp.nativo) {
      sp.nativo.onclick = function () {
        // Un rifiuto dell'utente (chiude il foglio di sistema) arriva qui
        // come errore: non e' un guasto, non si avvisa di nulla.
        navigator.share({ title: T("condividi_foto"), url: url })
          .catch(function () {});
      };
    }
    spShareBtnAttivo = bottone || null;
    sp.root.classList.add("open");
    sp.root.setAttribute("aria-hidden", "false");
    sp.copyBtn.focus();
  }

  function chiudiPannelloCondivisione() {
    if (!sp || !sp.root.classList.contains("open")) return;
    sp.root.classList.remove("open");
    sp.root.setAttribute("aria-hidden", "true");
    if (spShareBtnAttivo) {
      if (getComputedStyle(spShareBtnAttivo).display !== "none") { spShareBtnAttivo.focus(); }
      spShareBtnAttivo = null;
    }
  }

  /* Get-or-create del link di condivisione di una fotografia (o di una
     selezione di piu' fotografie) e apertura del pannello condiviso.
     endpoint e' l'indirizzo da chiamare (l'admin usa
     /admin/tree/media/{id}/share con CSRF, la griglia pubblica usa
     /condividi/{id} senza CSRF ne' corpo, la condivisione di selezione usa
     /condividi/selezione con gli ids nel corpo). anteprima e' {src, alt} da
     mostrare nel pannello (puo' essere null: la condivisione di selezione
     non ha un'unica immagine da mostrare): non si legge piu' solo da
     items[current] del visualizzatore, perche' la chiamata puo' arrivare
     anche dalla griglia, dove non ci sono items/current. cache e' l'oggetto
     {url} dove si tiene il token gia' ottenuto, per non richiederlo due
     volte. ancoraValida (se data) e' richiamata prima di mostrare il
     pannello: nel visualizzatore serve a scartare la risposta se nel
     frattempo si e' passati a un'altra foto (next/prev/Home/End). campi (se
     dato) e' un oggetto di coppie chiave/valore aggiunte al corpo del POST
     oltre a csrf_token, usato dalla condivisione di selezione per mandare
     gli ids. */
  function apriPannelloCondivisione(endpoint, csrfToken, bottone, anteprima, cache, ancoraValida, campi) {
    if (cache.url) {
      mostraPannelloCondivisione(cache.url, bottone, anteprima || cache.anteprima); return;
    }
    // Il collegamento lo prepara il server: finche' non torna, il bottone
    // resta premuto ma muto. La classe lo mostra occupato, altrimenti si
    // preme di nuovo credendo che il primo tocco non sia arrivato.
    bottone.disabled = true;
    bottone.classList.add("in-attesa");
    var fd = new FormData();
    if (csrfToken) fd.append("csrf_token", csrfToken);
    if (campi) {
      Object.keys(campi).forEach(function (k) { fd.append(k, campi[k]); });
    }
    fetch(endpoint, { method: "POST", body: fd })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        bottone.disabled = false;
        bottone.classList.remove("in-attesa");
        if (ancoraValida && !ancoraValida()) return;
        if (!d || !d.ok) { PC.avviso(T("condividi_ko")); return; }
        cache.url = d.url;
        // Se chi chiama non ha una propria anteprima da mostrare (la
        // condivisione di una selezione non ha un'unica foto), si usa
        // quella scelta a caso dal server fra le foto davvero condivise.
        if (!anteprima && d.anteprima) {
          cache.anteprima = { src: d.anteprima,
                              alt: d.conta ? T("condividi_conta", {n: d.conta}) : "" };
        }
        mostraPannelloCondivisione(d.url, bottone, anteprima || cache.anteprima);
      })
      .catch(function () {
        bottone.disabled = false;
        bottone.classList.remove("in-attesa");
        if (ancoraValida && !ancoraValida()) return;
        PC.avviso(T("condividi_ko"));
      });
  }

  function initLightbox() {
    var current = 0;
    var lb = build();
    document.body.appendChild(lb.root);
    var shareCache = {};

    items.forEach(function (it, i) {
      it.setAttribute("tabindex", "0");
      it.setAttribute("role", "button");
      it.addEventListener("click", function (ev) {
        // .sel-box e .share-box fermano gia' la propria propagazione, ma
        // questo controllo resta come rete di sicurezza (es. click
        // sintetici da tastiera che non passano dallo stesso percorso):
        // nessuno dei due deve mai aprire il visualizzatore ne' attivare
        // la selezione multipla, in nessuna modalita', selecting compresa.
        if (ev.target.classList.contains("sel-box") ||
            ev.target.classList.contains("share-box")) return;
        // Nei risultati di ricerca ogni foto porta il collegamento alla
        // propria cartella: cliccandolo si apre la cartella, non il
        // visualizzatore.
        if (ev.target.closest("a")) return;
        ev.preventDefault();
        if (selecting) { toggle(it); return; }
        open(i);
      });
      it.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); it.click(); }
      });
    });

    function open(i) {
      current = i; render();
      lb.root.classList.add("open");
      lb.root.setAttribute("aria-hidden", "false");
      document.body.style.overflow = "hidden";
      lb.closeBtn.focus();
    }
    function close() {
      if (sp && sp.root.classList.contains("open")) chiudiPannelloCondivisione();
      stopVideo();
      lb.root.classList.remove("open");
      lb.root.setAttribute("aria-hidden", "true");
      document.body.style.overflow = "";
      if (items[current]) items[current].focus();
    }
    function next() { current = (current + 1) % items.length; render(); }
    function prev() { current = (current - 1 + items.length) % items.length; render(); }
    function stopVideo() {
      try { lb.video.pause(); lb.video.removeAttribute("src"); lb.video.load(); } catch (e) {}
    }

    function render() {
      stopVideo();
      var it = items[current];
      var kind = it.getAttribute("data-kind");
      var dl = it.getAttribute("data-download");
      if (kind === "video") {
        lb.img.style.display = "none";
        lb.video.style.display = "block";
        lb.video.src = it.getAttribute("data-video");
        lb.video.play().catch(function () {});
      } else {
        lb.video.style.display = "none";
        lb.img.style.display = "block";
        lb.img.src = sorgenteDi(it);
        lb.img.alt = it.getAttribute("data-alt") || "";
      }
      lb.conta.textContent = T("di", {a: current + 1, b: items.length});
      if (dl) { lb.dl.href = dl; lb.dl.style.display = "inline-flex"; }
      else { lb.dl.style.display = "none"; }
      if (lb.share) {
        lb.share.style.display = "inline-flex";
        lb.share.textContent = T("condividi_foto");
        lb.share.disabled = false;
      }
      if (lb.shareTop) { lb.shareTop.disabled = false; }
      // Il link condiviso vale per una foto sola: cambiando foto si azzera
      // la cache e si chiude il pannello, cosi' non si manda in giro per
      // sbaglio il link di quella precedente.
      shareCache = {};
      chiudiPannelloCondivisione();
      precarica(current + 1); precarica(current - 1);
    }

    /* Bottoni "Condividi questa foto", pubblici come il loro equivalente
       nella griglia (.share-box). Usano il pannello di condivisione unico
       e l'endpoint pubblico /condividi/{id}, senza CSRF. */
    if (lb.share) {
      lb.share.addEventListener("click", function () { apriShareLightbox(lb.share); });
    }
    if (lb.shareTop) {
      lb.shareTop.addEventListener("click", function () { apriShareLightbox(lb.shareTop); });
    }

    /* "Metti in copertina": manda l'identificativo della fotografia aperta
       al pannello, che controlla che appartenga davvero a quest'album. Il
       riscontro e' scritto sul bottone stesso, dove sta guardando chi ha
       appena premuto. */
    if (lb.copertina) {
      lb.copertina.addEventListener("click", function () {
        var it = items[current];
        var id = it && it.getAttribute("data-id");
        var campo = document.getElementById("csrf");
        var griglia = document.querySelector(".photo-grid");
        var nodo = griglia && griglia.getAttribute("data-node-id");
        if (!id || !campo || !nodo) return;
        var fd = new FormData();
        fd.append("csrf_token", campo.value);
        fd.append("media_id", id);
        lb.copertina.disabled = true;
        lb.copertina.classList.add("in-attesa");
        fetch("/admin/tree/" + nodo + "/copertina", { method: "POST", body: fd })
          .then(function (r) { return r.json().catch(function () { return null; }); })
          .then(function (d) {
            lb.copertina.disabled = false;
            lb.copertina.classList.remove("in-attesa");
            if (!d || !d.ok) { PC.avviso(T("copertina_ko")); return; }
            lb.copertina.textContent = T("copertina_fatta");
            setTimeout(function () {
              lb.copertina.textContent = T("copertina_metti");
            }, 2000);
          })
          .catch(function () {
            lb.copertina.disabled = false;
            lb.copertina.classList.remove("in-attesa");
            PC.avviso(T("copertina_ko"));
          });
      });
    }

    function apriShareLightbox(bottone) {
      var it = items[current];
      var id = it && it.getAttribute("data-id");
      if (!id) return;
      var anteprima = {
        src: lb.img.style.display !== "none" ? lb.img.src : "",
        alt: (it && it.getAttribute("data-alt")) || ""
      };
      // La risposta puo' arrivare dopo che si e' passati ad un'altra foto
      // (next/prev/Home/End): se la foto corrente non e' piu' quella per
      // cui e' stato chiesto il link, il risultato va scartato senza
      // toccare la cache ne' riaprire il pannello.
      apriPannelloCondivisione(
        "/condividi/" + id, null, bottone, anteprima,
        shareCache, function () { return items[current] === it; });
    }

    /* Quale immagine si mostra a schermo intero. Su telefono basta il
       formato da 1280 punti: l'anteprima piena pesa il doppio e va
       preparata sul momento, mentre il 1280 e' gia' pronto sul disco. */
    function sorgenteDi(it) {
      var grande = it.getAttribute("data-preview") || "";
      if (!grande) return "";
      var medio = grande.replace("/preview/", "/thumb2x/");
      return (window.innerWidth <= 900 && window.devicePixelRatio <= 2) ? medio : grande;
    }

    /* Le vicine si preparano mentre si guarda quella di adesso, cosi'
       scorrere e' immediato. Deve scaricare ESATTAMENTE quello che poi
       verra' mostrato: prima chiedeva sempre l'anteprima piena, quindi su
       telefono tirava giu' due immagini da centotrentotto chilobyte che
       nessuno avrebbe mai visto — e intanto quella che serviva davvero
       restava da scaricare al momento del bisogno. */
    function precarica(i) {
      if (i < 0 || i >= items.length) return;
      var it = items[i];
      if (it.getAttribute("data-kind") === "video") return;
      var u = sorgenteDi(it);
      if (u) { var im = new Image(); im.src = u; }
    }

    lb.closeBtn.addEventListener("click", close);
    lb.nextBtn.addEventListener("click", next);
    lb.prevBtn.addEventListener("click", prev);
    lb.root.addEventListener("click", function (e) { if (e.target === lb.root) close(); });

    var x0 = null, y0 = null;
    lb.root.addEventListener("touchstart", function (e) {
      if (e.touches.length !== 1) return;
      x0 = e.touches[0].clientX; y0 = e.touches[0].clientY;
    }, { passive: true });
    lb.root.addEventListener("touchend", function (e) {
      if (x0 === null) return;
      var dx = e.changedTouches[0].clientX - x0;
      var dy = e.changedTouches[0].clientY - y0;
      if (Math.abs(dx) > 55 && Math.abs(dx) > Math.abs(dy) * 1.5) {
        if (dx < 0) next(); else prev();
      } else if (dy > 90 && Math.abs(dy) > Math.abs(dx) * 1.5) {
        close();
      }
      x0 = y0 = null;
    }, { passive: true });

    document.addEventListener("keydown", function (e) {
      if (!lb.root.classList.contains("open")) return;
      if (e.key === "Escape") {
        // Il pannello di condivisione si chiude con il primo Escape; il
        // visualizzatore solo quando il pannello e' gia' chiuso. Il
        // pannello ha gia' un suo listener Escape (buildSharePanel), ma
        // quello del visualizzatore va soppresso finche' il pannello e'
        // aperto: altrimenti un solo Escape chiuderebbe entrambi insieme.
        if (sp && sp.root.classList.contains("open")) return;
        close();
      }
      else if (e.key === "ArrowRight") next();
      else if (e.key === "ArrowLeft") prev();
      else if (e.key === "Home") { current = 0; render(); }
      else if (e.key === "End") { current = items.length - 1; render(); }
    });
  }

  function build() {
    var root = document.createElement("div");
    root.className = "lightbox";
    root.setAttribute("aria-hidden", "true");
    root.setAttribute("role", "dialog");
    root.setAttribute("aria-modal", "true");
    root.setAttribute("aria-label", T("visualizzatore"));
    var img = document.createElement("img");
    var video = document.createElement("video");
    video.setAttribute("controls", "");
    video.setAttribute("playsinline", "");
    video.style.display = "none";
    video.className = "lb-video";
    var closeBtn = mk("button", "lb-close", "&times;", T("chiudi"));
    var prevBtn = mk("button", "lb-nav prev", "&#8249;", T("precedente"));
    var nextBtn = mk("button", "lb-nav next", "&#8250;", T("successiva"));
    var conta = document.createElement("div");
    conta.className = "lb-count";
    var topbar = document.createElement("div");
    topbar.className = "lb-topbar";
    topbar.appendChild(conta);
    var actions = document.createElement("div");
    actions.className = "lb-actions";
    var dl = document.createElement("a");
    dl.className = "btn btn-accent";
    dl.textContent = T("scarica_orig");
    dl.setAttribute("download", "");
    // Una fotografia sola pesa pochi megabyte: dentro una webview di iOS
    // si passa dallo stesso percorso dello zip (l'unico che li' salva
    // davvero), ma senza mai anticipare istruzioni a chi non ne ha
    // bisogno — il riquadro compare solo quando serve. Fuori dalle
    // webview non cambia niente: l'attributo download e il click nativo
    // del browser bastano da soli, come hanno sempre fatto.
    dl.addEventListener("click", function (e) {
      if (webviewLimitata()) {
        e.preventDefault();
        percorsoWebview(dl.href, 1);
      }
    });
    actions.appendChild(dl);

    // "Acquista foto": solo se l'album ha la vendita attiva (Fase 1,
    // solo informativo — nessun pagamento reale ancora).
    var grid = document.querySelector(".photo-grid");
    if (grid && grid.dataset.sales === "1") {
      var acquista = mk("button", "btn btn-ghost", "", T("acquista_foto"));
      acquista.textContent = T("acquista_foto");
      acquista.addEventListener("click", function () {
        alert(T("acquisto_in_arrivo"));
      });
      actions.appendChild(acquista);
    }

    // Il bottone "Condividi questa foto" (sotto la foto) e il suo gemello
    // piccolo in alto a sinistra (solo da tablet in su) sono pubblici,
    // come il loro equivalente nella griglia (.share-box): chiamano
    // l'endpoint pubblico /condividi/{id}, senza CSRF.
    var share = mk("button", "btn btn-accent", "", T("condividi_foto"));
    share.textContent = T("condividi_foto");
    actions.appendChild(share);

    var shareTop = mk("button", "lb-share-top", "&#8599;", T("condividi_foto"));
    topbar.appendChild(shareTop);

    // "Metti in copertina": solo per chi amministra, e solo se la pagina
    // porta il campo di sicurezza (che c'e' unicamente quando si e'
    // entrati). Sta qui perche' la copertina si sceglie guardando la
    // fotografia grande, non da un elenco di nomi di file.
    var copertina = null;
    if (document.getElementById("csrf")) {
      copertina = mk("button", "btn btn-ghost", "", T("copertina_metti"));
      copertina.textContent = T("copertina_metti");
      actions.appendChild(copertina);
    }

    // Il pannello di condivisione (anteprima, link, bottoni social) e'
    // unico per tutta la pagina (buildSharePanel/document.body), non piu'
    // costruito qui: lo usano sia questi bottoni sia quelli della griglia.

    [img, video, closeBtn, prevBtn, nextBtn, topbar, actions].forEach(function (el) {
      root.appendChild(el);
    });
    return { root: root, img: img, video: video, closeBtn: closeBtn,
             prevBtn: prevBtn, nextBtn: nextBtn, dl: dl, conta: conta,
             share: share, shareTop: shareTop, copertina: copertina };
  }

  function mk(t, c, h, l) {
    var e = document.createElement(t);
    e.className = c; e.innerHTML = h; e.type = "button";
    if (l) e.setAttribute("aria-label", l);
    return e;
  }

  /* Gli altri collegamenti che chiedono un archivio: quelli delle
     fotografie preferite, uno per album piu' quello della barra, che non
     hanno un identificativo fisso da agganciare uno per uno. Marcati con
     data-zip, passano da qui e quindi dallo stesso percorso di tutti gli
     altri — avviso di attesa compreso, e riquadro del pannello di
     condivisione dentro il browser interno delle app su iPhone, dove
     altrimenti resterebbero link che non salvano niente. */
  function agganciaAltriArchivi() {
    document.addEventListener("click", function (e) {
      var a = e.target.closest ? e.target.closest("a[data-zip]") : null;
      if (!a || !a.getAttribute("href")) return;
      e.preventDefault();
      avviaZip(a.getAttribute("href") + "&",
               a, parseInt(a.getAttribute("data-quante"), 10) || 0);
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    initLazyLoad();
    initGrid();
    agganciaAltriArchivi();
  });
})();
