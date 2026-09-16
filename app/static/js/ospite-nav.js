/* Sostituisce "Accedi" con il nome di chi ha scelto delle fotografie. */
(function () {
  "use strict";
  function applica() {
    var m = document.cookie.match(/(?:^|;\s*)pc_nome=([^;]+)/);
    if (!m) return;
    var v = decodeURIComponent(m[1]);
    if (!v || v === "nessuno") return;
    var etichetta = v.indexOf("nome:") === 0 ? v.substring(5) : ("@" + v);
    /* Due punti da aggiornare: la barra larga e il pannello del menu su
       telefono. Prima se ne cambiava uno solo e sul telefono restava
       scritto "Accedi" anche a chi aveva gia' scelto le sue foto. */
    var punti = [document.getElementById("navAccedi"),
                 document.getElementById("navAccediMobile")].filter(Boolean);
    if (!punti.length) {
      var solo = document.querySelector("a.nav-admin");
      if (solo) punti.push(solo);
    }
    punti.forEach(function (a) {
      a.textContent = etichetta;
      a.href = "/mie-preferite";
      a.classList.add("nav-ospite");
    });
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", applica);
  } else {
    applica();
  }
})();
