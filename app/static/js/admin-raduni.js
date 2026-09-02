/* Gestione del calendario pubblico dei raduni. */
(function () {
  "use strict";
  var csrf;

  function eco(testo, ok) {
    var e = document.getElementById("r-eco");
    if (!e) return;
    e.textContent = testo;
    e.classList.toggle("ok", ok !== false);
    setTimeout(function () { e.textContent = ""; }, 3000);
  }

  function invia(indirizzo, dati, poi) {
    var fd = new FormData();
    fd.append("csrf_token", csrf);
    Object.keys(dati).forEach(function (k) { fd.append(k, dati[k]); });
    fetch(indirizzo, { method: "POST", body: fd })
      .then(function (r) {
        if (!r.ok) return r.json().then(function (d) {
          throw new Error(d.detail || "errore");
        });
        return r.json();
      })
      .then(poi)
      .catch(function (e) { PC.avviso(e.message || "Operazione non riuscita."); });
  }

  // Ricerca album: riusa l'API di ricerca gia' usata dal pannello ad
  // albero (/admin/tree/api/cerca), niente da costruire da capo.
  var timerCerca = null;
  function collegaRicercaAlbum(radunoId) {
    var campo = document.querySelector('[data-cerca-album="' + radunoId + '"]');
    var box = document.querySelector('[data-risultati-album="' + radunoId + '"]');
    if (!campo || !box) return;

    campo.addEventListener("input", function () {
      var q = campo.value.trim();
      clearTimeout(timerCerca);
      if (q.length < 2) { box.hidden = true; box.innerHTML = ""; return; }
      timerCerca = setTimeout(function () {
        fetch("/admin/tree/api/cerca?q=" + encodeURIComponent(q))
          .then(function (r) { return r.json(); })
          .then(function (lista) {
            box.innerHTML = "";
            if (!lista.length) {
              box.hidden = false;
              box.innerHTML = '<p class="up-hint">Nessun album trovato.</p>';
              return;
            }
            lista.forEach(function (n) {
              var voce = document.createElement("button");
              voce.type = "button";
              voce.className = "rad-album-voce";
              voce.textContent = n.title + (n.parent_path ? " — " + n.parent_path : "")
                + (n.is_private ? " (privato)" : "") + (n.hidden ? " (nascosto)" : "");
              voce.addEventListener("click", function () {
                invia("/admin/raduni/" + radunoId + "/album/collega",
                      { node_id: n.id }, function () { location.reload(); });
              });
              box.appendChild(voce);
            });
            box.hidden = false;
          });
      }, 250);
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    csrf = document.getElementById("csrf").value;

    var salvaAvviso = document.getElementById("r-salva-avviso");
    if (salvaAvviso) salvaAvviso.addEventListener("click", function () {
      invia("/admin/raduni/avviso",
            { avviso: document.getElementById("r-avviso").value },
            function () { eco("Salvato"); });
    });

    document.getElementById("r-aggiungi").addEventListener("click", function () {
      var data = document.getElementById("r-data").value;
      var luogo = document.getElementById("r-luogo").value.trim();
      if (!data || !luogo) { PC.avviso("Servono almeno data e luogo."); return; }
      invia("/admin/raduni/aggiungi", {
        data: data,
        ora: document.getElementById("r-ora").value,
        luogo: luogo,
        note: document.getElementById("r-note").value,
        mappa: document.getElementById("r-mappa").value.trim()
      }, function () { location.reload(); });
    });

    document.querySelectorAll("[data-salva-mappa]").forEach(function (b) {
      b.addEventListener("click", function () {
        var id = b.getAttribute("data-salva-mappa");
        var campo = document.querySelector('[data-mappa="' + id + '"]');
        invia("/admin/raduni/" + id + "/mappa", { mappa: campo.value.trim() },
              function () { location.reload(); });
      });
    });

    document.querySelectorAll("[data-elimina]").forEach(function (b) {
      b.addEventListener("click", function () {
        if (!confirm("Eliminare questo appuntamento? Gli eventuali album collegati non vengono toccati: si perde solo il legame con questo appuntamento.")) return;
        invia("/admin/raduni/" + b.getAttribute("data-elimina") + "/elimina",
              {}, function () { location.reload(); });
      });
    });

    document.querySelectorAll("[data-rimuovi-album]").forEach(function (b) {
      b.addEventListener("click", function () {
        var radunoId = b.getAttribute("data-rimuovi-album");
        var nodeId = b.getAttribute("data-node");
        invia("/admin/raduni/" + radunoId + "/album/" + nodeId + "/rimuovi",
              {}, function () { location.reload(); });
      });
    });

    document.querySelectorAll("[data-raduno-album]").forEach(function (el) {
      collegaRicercaAlbum(el.getAttribute("data-raduno-album"));
    });
  });
})();
