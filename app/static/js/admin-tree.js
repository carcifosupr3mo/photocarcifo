/* Gestione album: griglia card + menu contestuale */
(function () {
  "use strict";
  var CSRF = "", stack = [{ id: "root", title: "Tutte le categorie" }];

  document.addEventListener("DOMContentLoaded", function () {
    CSRF = document.getElementById("csrf").value;
    load("root");
    document.addEventListener("click", function (e) {
      if (!e.target.closest(".card-menu")) closeMenus();
    });
  });

  function closeMenus() {
    document.querySelectorAll(".menu-pop.open").forEach(function (m) {
            m.classList.remove("open");
            var c = m.closest(".acard"); if (c) c.classList.remove("menu-aperto");
          });
  }

  function load(parentId) {
    var grid = document.getElementById("grid");
    grid.innerHTML = "<p class='tree-hint'>Caricamento…</p>";
    fetch("/admin/tree/api/children?parent=" + encodeURIComponent(parentId))
      .then(function (r) { return r.json(); })
      .then(function (nodes) {
        grid.innerHTML = "";
        if (!nodes.length) { grid.innerHTML = "<p class='tree-hint'>Nessun album qui.</p>"; return; }
        nodes.forEach(function (n) { grid.appendChild(card(n)); });
        renderCrumbs();
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
      "<div class='acard-cover'>" + cover + "<div class='acard-badges'>" + badges + "</div></div>" +
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

    el.querySelector(".acard-cover").addEventListener("click", function () { openNode(n); });
    el.querySelector(".acard-txt").addEventListener("click", function () { openNode(n); });

    pop.querySelectorAll("[data-a]").forEach(function (b) {
      b.addEventListener("click", function (e) {
        e.stopPropagation(); closeMenus();
        var a = b.getAttribute("data-a");
        if (a === "open") openNode(n);
        else if (a === "rename") doRename(n);
        else if (a === "share") doShare(n);
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
      h += "<div class='det-block'><label>Visibilità</label><div class='det-row'>";
      h += "<button class='btn' data-s='priv' type='button'>" + (d.is_private ? "Rendi pubblico" : "Rendi privato") + "</button></div></div>";
      if (d.is_private) {
        h += "<div class='det-block'><label>Link di condivisione</label>";
        h += "<input type='text' id='d-link' readonly value='" + esc(link) + "'>";
        h += "<div class='det-row'>";
        h += "<button class='btn' data-s='copia' type='button'>Copia link</button>";
        h += "<button class='btn btn-ghost' data-s='regen' type='button'>Nuovo link</button>";
        h += "</div><span class='copia-eco' id='copiaEco'></span></div>";
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
          else if (a === "setscad") post(d.id + "/scadenza", { giorni: inner.querySelector("#d-scad").value });
          else if (a === "setpw") post(d.id + "/password", { password: inner.querySelector("#d-pw").value });
          else if (a === "clearpw") post(d.id + "/password", { clear: "1" });
        });
      });
    });
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
