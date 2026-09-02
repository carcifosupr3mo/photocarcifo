(function () {
  "use strict";
  var box, inner, csrf, nodoAperto = null, titoloAperto = "";

  document.addEventListener("DOMContentLoaded", function () {
    box = document.getElementById("sheet");
    inner = document.getElementById("sheetInner");
    csrf = document.getElementById("csrf").value;

    document.querySelectorAll("[data-pref]").forEach(function (b) {
      b.addEventListener("click", function () {
        nodoAperto = b.getAttribute("data-pref");
        titoloAperto = b.getAttribute("data-titolo");
        carica(b);
      });
    });

    box.addEventListener("click", function (e) { if (e.target === box) chiudi(); });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !box.hidden) chiudi();
    });

    inner.addEventListener("click", function (e) {
      var t = e.target.closest("[data-azione]");
      if (t) { azione(t); return; }
      if (e.target.classList.contains("sheet-close")) chiudi();
    });
  });

  function chiudi() { box.hidden = true; box.classList.remove("open"); }

  function carica(bottone) {
    if (bottone) bottone.disabled = true;
    fetch("/admin/preferiti/" + nodoAperto)
      .then(function (r) { return r.json(); })
      .then(function (d) {
        disegna(d);
        box.hidden = false;
        box.classList.add("open");
        if (bottone) bottone.disabled = false;
      })
      .catch(function () {
        PC.avviso("Non riesco a leggere le scelte.");
        if (bottone) bottone.disabled = false;
      });
  }

  function disegna(d) {
    var h = "<button class='sheet-close' type='button' aria-label='Chiudi'>&times;</button>";
    h += "<h3>" + titoloAperto + "</h3>";
    if (!d.persone || !d.persone.length) {
      h += "<p style='color:var(--ink-soft);'>Nessuna scelta in questo album.</p>";
      inner.innerHTML = h;
      return;
    }
    h += "<p style='color:var(--ink-soft);font-size:.82rem;margin-bottom:.8rem;'>" +
         d.persone.length + (d.persone.length === 1 ? " cliente ha" : " clienti hanno") +
         " scelto " + d.totale + " fotografie.</p>";
    h += "<button class='btn btn-ghost' type='button' data-azione='tutto' " +
         "style='margin-bottom:1rem;'>Cancella tutte le scelte di questo album</button>";
    d.persone.forEach(function (p, i) {
      h += "<div class='pref-persona'>";
      h += "<h4>";
      var ig = p.instagram || "";
      if (ig.indexOf("nome:") === 0) {
        h += ig.substring(5);
      } else if (ig && ig !== "nessuno") {
        h += "<a class='pref-ig' href='https://instagram.com/" + ig +
             "' target='_blank' rel='noopener'>@" + ig + "</a>";
      } else {
        h += "Cliente " + (i + 1);
      }
      h += " <span style='font-weight:400;color:var(--ink-soft);font-size:.74rem;'>(" + p.codice + ")</span></h4>";
      h += "<div class='meta'>" + p.quante + " fotografie — dal " + (p.dal || "").substring(0, 10) + "</div>";
      h += "<div class='pref-griglia-foto'>";
      p.ids.forEach(function (mid) {
        h += "<div class='pref-foto'>";
        h += "<a href='/preview/" + mid + "' target='_blank'>" +
             "<img src='/thumb/" + mid + "' loading='lazy' alt='Fotografia scelta'></a>";
        h += "<button class='pref-x' type='button' title='Togli dai preferiti' " +
             "data-azione='una' data-ospite='" + p.codice + "' data-media='" + mid + "'>&times;</button>";
        h += "</div>";
      });
      h += "</div>";
      h += "<div class='det-row'>";
      h += "<a class='btn' href='/zip/select?ids=" + p.ids.join(",") + "'>Scarica queste " + p.quante + "</a>";
      h += "<button class='btn btn-ghost' type='button' data-azione='cliente' " +
           "data-ospite='" + p.codice + "'>Cancella scelte cliente</button>";
      h += "</div></div>";
    });
    inner.innerHTML = h;
  }

  function azione(t) {
    var tipo = t.getAttribute("data-azione");
    var messaggi = {
      una: "Togliere questa fotografia dai preferiti del cliente?",
      cliente: "Cancellare tutte le scelte di questo cliente?",
      tutto: "Cancellare tutte le scelte di questo album?"
    };
    if (!confirm(messaggi[tipo])) return;
    t.disabled = true;
    var fd = new FormData();
    fd.append("csrf_token", csrf);
    if (tipo === "una") {
      fd.append("ospite", t.getAttribute("data-ospite"));
      fd.append("media_id", t.getAttribute("data-media"));
    } else if (tipo === "cliente") {
      fd.append("ospite", t.getAttribute("data-ospite"));
    }
    fetch("/admin/preferiti/" + nodoAperto + "/rimuovi", { method: "POST", body: fd })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.restano === 0) { location.reload(); return; }
        carica(null);
      })
      .catch(function () { PC.avviso("Operazione non riuscita."); t.disabled = false; });
  }
})();