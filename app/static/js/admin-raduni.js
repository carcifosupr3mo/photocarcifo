/* Gestione del calendario riservato dei raduni. */
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

  document.addEventListener("DOMContentLoaded", function () {
    csrf = document.getElementById("csrf").value;

    document.getElementById("r-salva").addEventListener("click", function () {
      invia("/admin/raduni/impostazioni", {
        domanda: document.getElementById("r-domanda").value,
        risposta: document.getElementById("r-risposta").value,
        avviso: document.getElementById("r-avviso").value
      }, function (d) {
        document.getElementById("r-risposta").value = "";
        eco(d.risposta_cambiata ? "Salvato, nuova risposta attiva" : "Salvato");
      });
    });

    document.getElementById("r-sblocca").addEventListener("click", function () {
      invia("/admin/raduni/sblocca", {}, function (d) {
        eco("Sbloccati " + d.sbloccati + " indirizzi");
      });
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
        if (!confirm("Eliminare questo appuntamento?")) return;
        invia("/admin/raduni/" + b.getAttribute("data-elimina") + "/elimina",
              {}, function () { location.reload(); });
      });
    });
  });
})();
