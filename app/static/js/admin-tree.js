/* Gestione album: griglia card + menu contestuale */
(function () {
  "use strict";
  var CSRF = "", stack = [{ id: "root", title: "Tutte le categorie" }];
  var selezionati = {}; // id -> true, solo per i nodi visibili nel livello corrente

  document.addEventListener("DOMContentLoaded", function () {
    CSRF = document.getElementById("csrf").value;
    load("root");
    document.addEventListener("click", function (e) {
      if (!e.target.closest(".card-menu")) closeMenus();
    });

    var searchForm = document.getElementById("searchForm");
    var searchInput = document.getElementById("searchInput");
    if (searchForm && searchInput) {
      var searchTimer = null;
      function avviaRicerca() {
        var q = searchInput.value.trim();
        if (!q) { load(stack[stack.length - 1].id); return; }
        cerca(q);
      }
      searchForm.addEventListener("submit", function (e) { e.preventDefault(); avviaRicerca(); });
      searchInput.addEventListener("input", function () {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(avviaRicerca, 300);
      });
    }

    var selAll = document.getElementById("selAll");
    if (selAll) {
      selAll.addEventListener("change", function () {
        document.querySelectorAll("#grid .acard-sel").forEach(function (cb) {
          cb.checked = selAll.checked;
          selezionati[cb.getAttribute("data-id")] = selAll.checked;
        });
        aggiornaToolbar();
      });
    }

    var toolbar = document.getElementById("bulkToolbar");
    if (toolbar) {
      toolbar.querySelectorAll("[data-bulk]").forEach(function (b) {
        b.addEventListener("click", function () { doBulk(b.getAttribute("data-bulk")); });
      });
    }
  });

  function idsSelezionati() {
    return Object.keys(selezionati).filter(function (k) { return selezionati[k]; });
  }

  function aggiornaToolbar() {
    var ids = idsSelezionati();
    var toolbar = document.getElementById("bulkToolbar");
    var count = document.getElementById("bulkCount");
    if (count) count.textContent = ids.length + " selezionat" + (ids.length === 1 ? "o" : "i");
    if (toolbar) toolbar.hidden = ids.length === 0;
    var selAll = document.getElementById("selAll");
    if (selAll) {
      var tot = document.querySelectorAll("#grid .acard-sel").length;
      selAll.checked = tot > 0 && ids.length === tot;
    }
  }

  var TESTI_AZIONE = {
    pubblico: "Rendere pubblici gli album selezionati?",
    privato: "Rendere privati gli album selezionati?\n\nI file sul NAS non vengono toccati.",
    nascondi: "Nascondere dal sito gli album selezionati?\n\nI file sul NAS non vengono toccati.",
    mostra: "Ripristinare sul sito gli album selezionati?"
  };

  function doBulk(azione) {
    var ids = idsSelezionati();
    if (!ids.length) return;
    var msg = TESTI_AZIONE[azione] || "Applicare l'azione agli album selezionati?";
    if (!confirm(msg)) return;
    var body = new URLSearchParams();
    body.append("csrf_token", CSRF);
    body.append("node_ids", ids.join(","));
    body.append("azione", azione);
    fetch("/admin/tree/bulk", { method: "POST", body: body })
      .then(function (r) { return r.json(); })
      .then(function () {
        selezionati = {};
        load(stack[stack.length - 1].id);
      })
      .catch(function () { PC.avviso("Operazione non riuscita."); });
  }

  function closeMenus() {
    document.querySelectorAll(".menu-pop.open").forEach(function (m) {
            m.classList.remove("open");
            var c = m.closest(".acard"); if (c) c.classList.remove("menu-aperto");
          });
  }

  function load(parentId) {
    var grid = document.getElementById("grid");
    grid.innerHTML = "<p class='tree-hint'>Caricamento…</p>";
    selezionati = {};
    aggiornaToolbar();
    fetch("/admin/tree/api/children?parent=" + encodeURIComponent(parentId))
      .then(function (r) { return r.json(); })
      .then(function (nodes) {
        grid.innerHTML = "";
        if (!nodes.length) { grid.innerHTML = "<p class='tree-hint'>Nessun album qui.</p>"; return; }
        nodes.forEach(function (n) { grid.appendChild(card(n)); });
        renderCrumbs();
        aggiornaToolbar();
      })
      .catch(function () {
        // Senza questo la griglia restava per sempre su "Caricamento…":
        // chi guardava non aveva modo di capire se stesse ancora
        // lavorando o si fosse piantata.
        grid.innerHTML = "<p class='tree-hint'>Non riesco a leggere gli album. " +
                         "Ricarica la pagina.</p>";
        PC.avviso("Non riesco a leggere gli album.");
      });
  }

  function cerca(q) {
    var grid = document.getElementById("grid");
    grid.innerHTML = "<p class='tree-hint'>Cerco…</p>";
    selezionati = {};
    aggiornaToolbar();
    fetch("/admin/tree/api/cerca?q=" + encodeURIComponent(q))
      .then(function (r) { return r.json(); })
      .then(function (risultati) {
        grid.innerHTML = "";
        if (!risultati.length) { grid.innerHTML = "<p class='tree-hint'>Nessun album trovato.</p>"; return; }
        risultati.forEach(function (n) { grid.appendChild(searchCard(n)); });
      })
      .catch(function () {
        grid.innerHTML = "<p class='tree-hint'>Ricerca non riuscita.</p>";
        PC.avviso("Ricerca non riuscita.");
      });
  }

  function searchCard(n) {
    var el = document.createElement("div");
    el.className = "acard";
    var cover = n.cover ? "<img data-src='/thumb/" + n.cover + "' alt=''>" : "";
    var badges = "";
    if (n.is_private) badges += "<span class='badge-private'>Privato</span>";
    if (n.hidden) badges += "<span class='badge-hidden'>Nascosto</span>";
    el.innerHTML =
      "<div class='acard-cover'>" + cover +
        "<div class='acard-badges'>" + badges + "</div></div>" +
      "<div class='acard-body'>" +
        "<div class='acard-txt'><h3>" + esc(n.title) + "</h3>" +
        "<p class='tree-path'>" + esc(n.parent_path || "") + "</p>" +
        "<p>" + n.total_media + " foto</p></div>" +
      "</div>";
    var img = el.querySelector("img");
    if (img) { img.src = img.getAttribute("data-src"); img.removeAttribute("data-src"); }
    el.querySelector(".acard-cover").addEventListener("click", function () { doShare(n); });
    el.querySelector(".acard-txt").addEventListener("click", function () { doShare(n); });
    return el;
  }

  function renderCrumbs() {
    var c = document.getElementById("crumbs");
    c.innerHTML = "";
    stack.forEach(function (s, i) {
      if (i > 0) { var sep = document.createElement("span"); sep.textContent = "/"; sep.className = "sep"; c.appendChild(sep); }
      if (i === stack.length - 1) {
        var cur = document.createElement("span"); cur.className = "current"; cur.textContent = s.title; c.appendChild(cur);
      } else {
        var a = document.createElement("a"); a.href = "#"; a.textContent = s.title;
        a.addEventListener("click", function (e) { e.preventDefault(); stack = stack.slice(0, i + 1); load(s.id); });
        c.appendChild(a);
      }
    });
  }

  function card(n) {
    var el = document.createElement("div");
    el.className = "acard";
    var cover = n.cover ? "<img data-src='/thumb/" + n.cover + "' alt=''>" : "";
    var badges = "";
    if (n.is_private) badges += "<span class='badge-private'>Privato</span>";
    if (n.hidden) badges += "<span class='badge-hidden'>Nascosto</span>";
    el.innerHTML =
      "<div class='acard-cover'>" + cover +
        "<label class='acard-sel-wrap' title='Seleziona'>" +
          "<input type='checkbox' class='acard-sel' data-id='" + n.id + "'>" +
        "</label>" +
        "<div class='acard-badges'>" + badges + "</div></div>" +
      "<div class='acard-body'>" +
        "<div class='acard-txt'><h3>" + esc(n.title) + "</h3>" +
        "<p>" + n.total_media + " foto</p></div>" +
        "<button class='card-menu' aria-label='Azioni' type='button'>⋮</button>" +
        "<div class='menu-pop'>" +
          "<button data-a='open' type='button'>Apri</button>" +
          "<button data-a='rename' type='button'>Rinomina</button>" +
          "<button data-a='share' type='button'>" + (n.is_private ? "Condivisione" : "Rendi privato") + "</button>" +
          "<button data-a='dl' type='button'>" + (n.downloads_enabled ? "Blocca download" : "Permetti download") + "</button>" +
          "<button data-a='hide' type='button'>" + (n.hidden ? "Mostra sul sito" : "Nascondi dal sito") + "</button>" +
          "<button data-a='cover' type='button'>Copertina</button>" +
          "<button data-a='qr' type='button'>QR code</button>" +
          "<button data-a='pref' type='button'>Foto preferite dal cliente</button>" +
          "<button data-a='trash' class='danger' type='button'>Sposta nel cestino</button>" +
        "</div>" +
      "</div>";

    var img = el.querySelector("img");
    if (img) { img.src = img.getAttribute("data-src"); img.removeAttribute("data-src"); }

    var menuBtn = el.querySelector(".card-menu");
    var pop = el.querySelector(".menu-pop");
    menuBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      var wasOpen = pop.classList.contains("open");
      closeMenus();
      if (!wasOpen) pop.classList.add("open");
    });

    var selBox = el.querySelector(".acard-sel");
    var selWrap = el.querySelector(".acard-sel-wrap");
    selBox.addEventListener("change", function () {
      selezionati[n.id] = selBox.checked;
      aggiornaToolbar();
    });
    selWrap.addEventListener("click", function (e) { e.stopPropagation(); });

    el.querySelector(".acard-cover").addEventListener("click", function () { openNode(n); });
    el.querySelector(".acard-txt").addEventListener("click", function () { openNode(n); });

    pop.querySelectorAll("[data-a]").forEach(function (b) {
      b.addEventListener("click", function (e) {
        e.stopPropagation(); closeMenus();
        var a = b.getAttribute("data-a");
        if (a === "open") openNode(n);
        else if (a === "rename") doRename(n);
        else if (a === "share") doShare(n);
        else if (a === "cover") doCover(n);
        else if (a === "qr") doQr(n);
        else if (a === "dl") post(n.id + "/downloads", { downloads_enabled: n.downloads_enabled ? "0" : "1" });
        else if (a === "pref") {
          fetch("/admin/preferiti/" + n.id)
            .then(function (r) { return r.json(); })
            .then(function (d) { mostraPreferiti(n, d); })
            .catch(function () { PC.avviso("Non riesco a leggere i preferiti."); });
        }
        else if (a === "trash") {
          if (confirm("Spostare l'album \"" + n.title + "\" nel cestino?\n\nI file restano sul NAS e si possono rimettere a posto dal pannello Cestino.")) {
            var fd = new FormData();
            fd.append("csrf_token", CSRF);
            fetch("/admin/trash/node/" + n.id, { method: "POST", body: fd })
              .then(function (r) { return r.json(); })
              .then(function () { location.reload(); })
              .catch(function () { PC.avviso("Operazione non riuscita."); });
          }
        }
        else if (a === "hide") {
          var msg = n.hidden ? "Ripristinare questo album sul sito?" :
            "Nascondere questo album dal sito?\n\nI file sul NAS non vengono toccati.";
          if (confirm(msg)) post(n.id + "/hide", { hidden: n.hidden ? "0" : "1" });
        }
      });
    });
    return el;
  }

  function openNode(n) {
    if (!n.has_children) { doShare(n); return; }
    stack.push({ id: n.id, title: n.title });
    load(n.id);
  }

  function doRename(n) {
    var t = prompt("Nome mostrato sul sito (i file sul NAS non cambiano):", n.title);
    if (t !== null && t.trim()) post(n.id + "/rename", { title: t.trim() });
  }

  function doShare(n) {
    fetch("/admin/tree/api/node?id=" + n.id).then(function (r) { return r.json(); }).then(function (d) {
      var s = document.getElementById("sheet"), inner = document.getElementById("sheetInner");
      var base = d.site_url || window.location.origin;
      var link = d.access_token ? (base + "/p/" + d.access_token) : "";
      var h = "<div class='sheet-head'><h2>" + esc(d.title) + "</h2><button id='sheetX' type='button'>&times;</button></div>";
      h += "<p class='tree-path'>" + esc(d.rel_path || "") + " — " + d.total_media + " foto</p>";
      h += "<div class='det-block'><label>Numeri di gara</label><div class='det-row'>";
      h += "<a class='btn btn-ghost' href='/admin/numeri/" + d.id + "'>Correggi i numeri</a></div></div>";
      h += "<div class='det-block'><label>Statistiche</label>";
      if (d.stats && d.stats.aperture) {
        h += "<div class='tree-path'>" + d.stats.aperture + " apertur" + (d.stats.aperture === 1 ? "a" : "e");
        if (d.stats.prima_apertura) h += " — dal " + d.stats.prima_apertura.substring(0, 10);
        if (d.stats.ultima_apertura) h += " — ultima il " + d.stats.ultima_apertura.substring(0, 10);
        h += "</div>";
      } else {
        h += "<div class='tree-path'>Nessuna apertura registrata.</div>";
      }
      h += "<div class='tree-path'>" + (d.stats ? d.stats.download : 0) + " download (singoli o zip)</div></div>";
      h += "<div class='det-block'><label>Visibilità</label><div class='det-row'>";
      h += "<button class='btn' data-s='priv' type='button'>" + (d.is_private ? "Rendi pubblico" : "Rendi privato") + "</button></div></div>";
      if (d.is_private) {
        h += "<div class='det-block'><label>Link di condivisione</label>";
        h += "<input type='text' id='d-link' readonly value='" + esc(link) + "'>";
        h += "<div class='det-row'>";
        h += "<button class='btn' data-s='copia' type='button'>Copia link</button>";
        h += "<button class='btn btn-ghost' data-s='regen' type='button'>Nuovo link</button>";
        h += "</div><span class='copia-eco' id='copiaEco'></span></div>";
        h += "<div class='det-block'><label>Condividi con cliente</label><div class='det-row'>";
        h += "<button class='btn' data-s='msgcopia' type='button'>Copia messaggio</button>";
        h += "<a class='btn btn-ghost' id='d-wa' target='_blank' rel='noopener'>WhatsApp</a>";
        h += "<a class='btn btn-ghost' id='d-tg' target='_blank' rel='noopener'>Telegram</a>";
        h += "</div><span class='copia-eco' id='msgEco'></span></div>";
        var statoScad = d.scaduto ? "SCADUTO"
          : (d.giorni_rimasti === null ? "senza scadenza"
             : ("scade fra " + d.giorni_rimasti + " giorni"));
        h += "<div class='det-block'><label>Validita del link — " + statoScad + "</label>";
        h += "<select id='d-scad'>";
        h += "<option value='0'" + (d.giorni_rimasti === null ? " selected" : "") + ">Senza scadenza</option>";
        h += "<option value='7'>7 giorni</option>";
        h += "<option value='30'>30 giorni</option>";
        h += "<option value='90'>90 giorni</option>";
        h += "<option value='180'>6 mesi</option>";
        h += "<option value='365'>1 anno</option>";
        h += "</select>";
        h += "<div class='det-row'><button class='btn' data-s='setscad' type='button'>Applica</button></div></div>";
        h += "<div class='det-block'><label>Password " + (d.has_password ? "(attiva)" : "(nessuna)") + "</label><div class='det-row'>";
        h += "<input type='password' id='d-pw' placeholder='Password'>";
        h += "<button class='btn' data-s='setpw' type='button'>Imposta</button>";
        if (d.has_password) h += "<button class='btn btn-ghost' data-s='clearpw' type='button'>Togli</button>";
        h += "</div></div>";
      }
      inner.innerHTML = h; s.hidden = false;
      // La Content-Security-Policy vieta gli attributi onclick scritti nella
      // pagina: la selezione del link va agganciata da qui.
      var campoLink = document.getElementById("d-link");
      if (campoLink) campoLink.addEventListener("click", function () { campoLink.select(); });
      // Messaggio per il cliente: mai la password, solo nome, link e
      // scadenza se c'e'. Composto qui perche' i dati (titolo, link,
      // giorni_rimasti) sono gia' tutti su questa pagina.
      var waLink = document.getElementById("d-wa"), tgLink = document.getElementById("d-tg");
      var messaggioCliente = "";
      if (waLink && tgLink && link) {
        if (d.scaduto) {
          messaggioCliente = "Ciao! Il link dell'album \"" + d.title + "\" e' scaduto: "
            + link + "\nFammi sapere che ne genero uno nuovo.\n— Photo Carcifo";
        } else {
          messaggioCliente = "Ciao! Ecco le foto dell'album \"" + d.title + "\": " + link;
          if (d.giorni_rimasti !== null && d.giorni_rimasti !== undefined) {
            messaggioCliente += "\n(link valido ancora " + d.giorni_rimasti + " giorni)";
          }
          messaggioCliente += "\n— Photo Carcifo";
        }
        waLink.href = "https://wa.me/?text=" + encodeURIComponent(messaggioCliente);
        tgLink.href = "https://t.me/share/url?url=" + encodeURIComponent(link) + "&text=" + encodeURIComponent(messaggioCliente);
      }
      document.getElementById("sheetX").addEventListener("click", function () { s.hidden = true; });
      s.addEventListener("click", function (e) { if (e.target === s) s.hidden = true; });
      inner.querySelectorAll("[data-s]").forEach(function (b) {
        b.addEventListener("click", function () {
          var a = b.getAttribute("data-s");
          if (a === "priv") post(d.id + "/privacy", { is_private: d.is_private ? "0" : "1" });
          else if (a === "regen") { if (confirm("Il link attuale smetterà di funzionare. Continuare?")) post(d.id + "/regen-link", {}); }
          else if (a === "copia") {
            var campo = inner.querySelector("#d-link");
            var testo = campo ? campo.value : "";
            var eco = inner.querySelector("#copiaEco");
            function fatto() {
              if (eco) { eco.textContent = "Copiato"; eco.classList.add("ok"); }
              setTimeout(function () { if (eco) { eco.textContent = ""; eco.classList.remove("ok"); } }, 2200);
            }
            if (navigator.clipboard && window.isSecureContext) {
              navigator.clipboard.writeText(testo).then(fatto).catch(function () {
                if (campo) { campo.select(); document.execCommand("copy"); fatto(); }
              });
            } else if (campo) {
              campo.select(); campo.setSelectionRange(0, 99999);
              document.execCommand("copy"); fatto();
            }
          }
          else if (a === "msgcopia") {
            var testoMsg = messaggioCliente;
            var ecoMsg = inner.querySelector("#msgEco");
            function fattoMsg() {
              if (ecoMsg) { ecoMsg.textContent = "Copiato"; ecoMsg.classList.add("ok"); }
              setTimeout(function () { if (ecoMsg) { ecoMsg.textContent = ""; ecoMsg.classList.remove("ok"); } }, 2200);
            }
            if (navigator.clipboard && window.isSecureContext) {
              navigator.clipboard.writeText(testoMsg).then(fattoMsg).catch(function () { window.prompt("Messaggio", testoMsg); });
            } else {
              window.prompt("Messaggio", testoMsg);
            }
          }
          else if (a === "setscad") post(d.id + "/scadenza", { giorni: inner.querySelector("#d-scad").value });
          else if (a === "setpw") post(d.id + "/password", { password: inner.querySelector("#d-pw").value });
          else if (a === "clearpw") post(d.id + "/password", { clear: "1" });
        });
      });
    });
  }

  function doCover(n) {
    fetch("/admin/tree/api/node?id=" + n.id).then(function (r) { return r.json(); }).then(function (d) {
      fetch("/admin/tree/api/media?node=" + n.id).then(function (r) { return r.json(); }).then(function (foto) {
        var s = document.getElementById("sheet"), inner = document.getElementById("sheetInner");
        var h = "<div class='sheet-head'><h2>Copertina — " + esc(d.title) + "</h2><button id='sheetX' type='button'>&times;</button></div>";
        h += "<div class='det-block'><label>Copertina attuale</label><div class='det-row'>";
        h += "<button class='btn btn-ghost' data-cov='auto'" + (!d.cover_media_id ? " disabled" : "") + ">Torna alla copertina automatica</button>";
        h += "</div></div>";
        if (!foto.length) {
          h += "<p class='tree-hint'>Nessuna fotografia diretta in questo album.</p>";
        } else {
          h += "<div class='det-block'><label>Scegli la fotografia</label>";
          h += "<div class='cover-pick'>";
          foto.forEach(function (m) {
            var sel = m.id === d.cover ? " sel" : "";
            h += "<button class='cover-pick-item" + sel + "' type='button' data-cov='" + m.id + "'>" +
                 "<img data-src='/thumb/" + m.id + "' alt=''></button>";
          });
          h += "</div></div>";
        }
        inner.innerHTML = h; s.hidden = false;
        inner.querySelectorAll("img[data-src]").forEach(function (img) {
          img.src = img.getAttribute("data-src"); img.removeAttribute("data-src");
        });
        document.getElementById("sheetX").addEventListener("click", function () { s.hidden = true; });
        s.addEventListener("click", function (e) { if (e.target === s) s.hidden = true; });
        inner.querySelectorAll("[data-cov]").forEach(function (b) {
          b.addEventListener("click", function () {
            var v = b.getAttribute("data-cov");
            post(n.id + "/copertina", { media_id: v === "auto" ? "" : v });
          });
        });
      }).catch(function () { PC.avviso("Non riesco a leggere le fotografie di questo album."); });
    }).catch(function () { PC.avviso("Non riesco a leggere l'album."); });
  }

  function doQr(n) {
    fetch("/admin/tree/api/node?id=" + n.id).then(function (r) { return r.json(); }).then(function (d) {
      var s = document.getElementById("sheet"), inner = document.getElementById("sheetInner");
      var base = d.site_url || window.location.origin;
      var link, bloccato = null;
      if (d.is_private) {
        if (!d.access_token) bloccato = "Questo album privato non ha ancora un link di condivisione: generane uno prima dal menu «Condivisione».";
        else link = base + "/p/" + d.access_token;
      } else if (d.hidden) {
        bloccato = "Questo album e' nascosto e non ha un indirizzo pubblico raggiungibile. Rendilo pubblico o privato con un link prima di creare il QR code.";
      } else {
        link = base + "/n/" + d.slug;
      }
      var h = "<div class='sheet-head'><h2>QR code — " + esc(d.title) + "</h2><button id='sheetX' type='button'>&times;</button></div>";
      if (bloccato) {
        h += "<p class='tree-hint'>" + esc(bloccato) + "</p>";
      } else {
        h += "<div class='det-block'><div class='det-row'>";
        h += "<img src='/admin/tree/" + n.id + "/qr' alt='QR code' width='220' height='220'>";
        h += "</div></div>";
        h += "<div class='det-block'><label>Link</label>";
        h += "<input type='text' id='d-qrlink' readonly value='" + esc(link) + "'>";
        h += "<div class='det-row'>";
        h += "<button class='btn' data-s='copia' type='button'>Copia link</button>";
        h += "<a class='btn btn-ghost' href='/admin/tree/" + n.id + "/qr?scarica=1' download='qr-" + esc(d.slug) + ".png'>Scarica PNG</a>";
        h += "</div><span class='copia-eco' id='copiaEco'></span></div>";
      }
      inner.innerHTML = h; s.hidden = false;
      var campoLink = document.getElementById("d-qrlink");
      if (campoLink) campoLink.addEventListener("click", function () { campoLink.select(); });
      document.getElementById("sheetX").addEventListener("click", function () { s.hidden = true; });
      s.addEventListener("click", function (e) { if (e.target === s) s.hidden = true; });
      var copiaBtn = inner.querySelector("[data-s='copia']");
      if (copiaBtn) {
        copiaBtn.addEventListener("click", function () {
          var campo = inner.querySelector("#d-qrlink");
          var testo = campo ? campo.value : "";
          var eco = inner.querySelector("#copiaEco");
          function fatto() {
            if (eco) { eco.textContent = "Copiato"; eco.classList.add("ok"); }
            setTimeout(function () { if (eco) { eco.textContent = ""; eco.classList.remove("ok"); } }, 2200);
          }
          if (navigator.clipboard && window.isSecureContext) {
            navigator.clipboard.writeText(testo).then(fatto).catch(function () {
              if (campo) { campo.select(); document.execCommand("copy"); fatto(); }
            });
          } else if (campo) {
            campo.select(); campo.setSelectionRange(0, 99999);
            document.execCommand("copy"); fatto();
          }
        });
      }
    }).catch(function () { PC.avviso("Non riesco a leggere l'album."); });
  }

  function post(path, data) {
    var body = new URLSearchParams();
    body.append("csrf_token", CSRF);
    Object.keys(data).forEach(function (k) { body.append(k, data[k]); });
    fetch("/admin/tree/" + path, { method: "POST", body: body })
      .then(function (r) { return r.json(); })
      .then(function () { location.reload(); })
      .catch(function () { PC.avviso("Operazione non riuscita."); });
  }

  function esc(s) {
    return (s || "").replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
})();


/* Elenco delle fotografie scelte dai clienti in un album. */
function mostraPreferiti(n, d) {
  var box = document.getElementById("sheet");
  var inner = document.getElementById("sheetInner");
  if (!box || !inner) return;
  var h = "<button class='sheet-close' type='button' aria-label='Chiudi'>&times;</button>";
  h += "<h3>" + n.title + "</h3>";
  if (!d.persone || !d.persone.length) {
    h += "<p style='color:var(--ink-soft);font-size:.88rem;'>" +
         "Nessun cliente ha ancora segnato fotografie in questo album.</p>";
  } else {
    h += "<p style='color:var(--ink-soft);font-size:.82rem;margin-bottom:1rem;'>" +
         d.persone.length + " " + (d.persone.length === 1 ? "persona ha" : "persone hanno") +
         " scelto " + d.totale + " fotografie.</p>";
    d.persone.forEach(function (p, i) {
      h += "<div class='pref-persona'>";
      var ig = p.instagram || "";
      h += "<h4>";
      if (ig.indexOf("nome:") === 0) { h += ig.substring(5); }
      else if (ig && ig !== "nessuno") {
        h += "<a class='pref-ig' href='https://instagram.com/" + ig +
             "' target='_blank' rel='noopener'>@" + ig + "</a>";
      } else { h += "Cliente " + (i + 1); }
      h += " <span style='font-weight:400;color:var(--ink-soft);font-size:.74rem;'>(" + p.codice + ")</span></h4>";
      h += "<div class='meta'>" + p.quante + " fotografie — dal " + (p.dal || "").substring(0, 10) + "</div>";
      h += "<a class='btn' href='/zip/select?ids=" + p.ids.join(",") + "'>Scarica queste " + p.quante + "</a>";
      h += "<div class='pref-nomi' style='margin-top:.7rem;'>" + p.nomi.join(", ") + "</div>";
      h += "</div>";
    });
  }
  inner.innerHTML = h;
  box.hidden = false;
  box.classList.add("open");
}


/* Chiusura della scheda: croce, tasto Esc, tocco fuori dal riquadro. */
function chiudiScheda() {
  var box = document.getElementById("sheet");
  if (!box) return;
  box.hidden = true;
  box.classList.remove("open");
}

document.addEventListener("click", function (e) {
  if (e.target.classList && e.target.classList.contains("sheet-close")) {
    e.preventDefault();
    chiudiScheda();
    return;
  }
  var box = document.getElementById("sheet");
  if (box && !box.hidden && e.target === box) chiudiScheda();
});

document.addEventListener("keydown", function (e) {
  if (e.key !== "Escape") return;
  var box = document.getElementById("sheet");
  if (box && !box.hidden) { chiudiScheda(); return; }
  document.querySelectorAll(".menu-pop.open").forEach(function (m) {
    m.classList.remove("open");
    var c = m.closest(".acard");
    if (c) c.classList.remove("menu-aperto");
  });
});
