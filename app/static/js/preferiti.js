/* Cuore sulle fotografie: il cliente segna quelle che preferisce. */
(function () {
  "use strict";
  var griglia, nodeId, scelte = {};

  document.addEventListener("DOMContentLoaded", function () {
    griglia = document.querySelector(".photo-grid");
    if (!griglia) return;
    nodeId = griglia.getAttribute("data-node-id");
    if (!nodeId) return;

    fetch("/preferiti/album/" + nodeId)
      .then(function (r) { return r.json(); })
      .then(function (d) {
        (d.ids || []).forEach(function (i) { scelte[i] = true; });
        disegna();
        aggiornaBarra(d.totale || 0);
      })
      .catch(disegna);
  });

  function disegna() {
    griglia.querySelectorAll(".photo").forEach(function (foto) {
      if (foto.querySelector(".cuore")) return;
      var id = foto.getAttribute("data-id");
      if (!id) return;
      var b = document.createElement("button");
      b.className = "cuore" + (scelte[id] ? " attivo" : "");
      b.type = "button";
      b.setAttribute("aria-label", T("pref_segna"));
      b.title = T("pref_segna");
      b.setAttribute("aria-pressed", scelte[id] ? "true" : "false");
      b.innerHTML = "<svg viewBox='0 0 24 24' aria-hidden='true'>" +
        "<path d='M12 20.4 4.6 13a4.6 4.6 0 0 1 6.5-6.5l.9.9.9-.9A4.6 4.6 0 0 1 19.4 13z'/></svg>";
      b.addEventListener("click", function (e) {
        e.preventDefault(); e.stopPropagation();
        if (window.preferitiRichiediNome && !scelte[id]) {
          window.preferitiRichiediNome(function () { segna(id, b); });
        } else {
          segna(id, b);
        }
      });
      foto.appendChild(b);
    });
  }

  function segna(id, bottone) {
    bottone.disabled = true;
    fetch("/preferiti/" + id, { method: "POST" })
      .then(function (r) {
        if (!r.ok) throw new Error("no");
        return r.json();
      })
      .then(function (d) {
        scelte[id] = d.attivo;
        bottone.classList.toggle("attivo", d.attivo);
        bottone.setAttribute("aria-pressed", d.attivo ? "true" : "false");
        aggiornaBarra(d.totale);
        bottone.disabled = false;
      })
      .catch(function () { bottone.disabled = false; PC.avvisoRete(); });
  }

  function aggiornaBarra(totale) {
    var b = document.getElementById("dlPref");
    if (!b) return;
    if (totale > 0) {
      b.style.display = "inline-flex";
      b.textContent = T("pref_scarica", {n: totale});
      var ids = Object.keys(scelte).filter(function (k) { return scelte[k]; });
      b.href = "/zip/select?ids=" + ids.join(",");
    } else {
      b.style.display = "none";
    }
  }
})();
