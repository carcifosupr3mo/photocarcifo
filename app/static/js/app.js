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

  /* Il download parte in un iframe invisibile, non con una vera
     navigazione (window.location.href): quando l'archivio e' pronto va
     bene lo stesso (Content-Disposition: attachment fa scaricare anche
     dentro un iframe), ma quando il server risponde 409 la risposta e'
     un JSON senza attachment, e window.location.href l'avrebbe mostrato
     al posto della pagina — cancellando lo script che deve leggere il
     biscottino del 409 proprio mentre arriva. Un solo iframe, riusato a
     ogni download invece che ricreato: la pagina non ne accumula uno per
     click. */
  function iframeZip() {
    var f = document.getElementById("pc-zip-iframe");
    if (!f) {
      f = document.createElement("iframe");
      f.id = "pc-zip-iframe";
      f.name = "pc-zip-iframe";
      f.style.display = "none";
      document.body.appendChild(f);
    }
    return f;
  }

  function avviaZip(indirizzo, bottone) {
    if (bottone && bottone.disabled) return;
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
    iframeZip().src = indirizzo + "&segnale=" + segno;
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
        avviaZip("/zip/select?ids=" + ids.join(","), btnDl);
      });
      // "Scarica tutto l'album": e' il pacco piu' pesante di tutti, quello
      // per cui l'attesa si fa sentire davvero.
      var btnTutto = document.getElementById("dlTutto");
      if (btnTutto) btnTutto.addEventListener("click", function (e) {
        e.preventDefault();
        avviaZip(btnTutto.getAttribute("href") + "?", btnTutto);
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
    actions.appendChild(dl);
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

  document.addEventListener("DOMContentLoaded", function () {
    initLazyLoad();
    initGrid();
  });
})();
