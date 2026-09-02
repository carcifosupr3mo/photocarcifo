/* Modo di visualizzazione delle fotografie: la scelta resta memorizzata. */
(function () {
  "use strict";
  var CHIAVE = "pc_vista";
  var VALIDE = ["griglia", "grande"];

  function salvata() {
    try {
      var v = localStorage.getItem(CHIAVE);
      return VALIDE.indexOf(v) !== -1 ? v : "griglia";
    } catch (e) { return "griglia"; }
  }

  function salva(v) {
    try { localStorage.setItem(CHIAVE, v); } catch (e) {}
  }

  document.addEventListener("DOMContentLoaded", function () {
    var griglia = document.querySelector(".photo-grid");
    var bottoni = document.querySelectorAll("[data-vista]");
    if (!griglia || !bottoni.length) return;

    function applica(v) {
      griglia.classList.remove("vista-griglia", "vista-grande");
      griglia.classList.add("vista-" + v);
      bottoni.forEach(function (b) {
        var suo = b.getAttribute("data-vista") === v;
        b.classList.toggle("attivo", suo);
        b.setAttribute("aria-pressed", suo ? "true" : "false");
      });
    }

    applica(salvata());

    bottoni.forEach(function (b) {
      b.addEventListener("click", function () {
        var v = b.getAttribute("data-vista");
        salva(v);
        applica(v);
      });
    });
  });
})();
