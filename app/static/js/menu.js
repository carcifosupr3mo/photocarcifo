/* Apertura e chiusura del menu su telefono.
 *
 * Il pannello e il velo sono gia' nella pagina, chiusi con l'attributo
 * hidden. Al primo avvio hidden viene tolto e sostituito dalla classe
 * "pronto": da quel momento la visibilita' e' governata dal foglio di
 * stile, che puo' animare l'apertura. Se questo script non partisse, hidden
 * resterebbe al suo posto e il menu semplicemente non si aprirebbe, senza
 * lasciare un riquadro spalancato in mezzo alla pagina.
 *
 * Si chiude toccando fuori, premendo Esc, scegliendo una voce e quando lo
 * schermo torna largo, perche' li' le voci sono di nuovo nella barra.
 */
(function () {
  "use strict";
  document.addEventListener("DOMContentLoaded", function () {
    var tasto = document.getElementById("menuTasto");
    var pannello = document.getElementById("menuPannello");
    var velo = document.getElementById("menuVelo");
    if (!tasto || !pannello) return;

    [pannello, velo].forEach(function (e) {
      if (!e) return;
      e.hidden = false;
      e.classList.add("pronto");
    });

    function aperto() { return pannello.classList.contains("aperto"); }

    function mostra(si) {
      [pannello, velo].forEach(function (e) {
        if (e) e.classList.toggle("aperto", si);
      });
      tasto.setAttribute("aria-expanded", si ? "true" : "false");
      tasto.classList.toggle("aperto", si);
      document.body.classList.toggle("menu-fermo", si);
    }

    tasto.addEventListener("click", function (e) {
      e.stopPropagation();
      mostra(!aperto());
    });

    if (velo) velo.addEventListener("click", function () { mostra(false); });

    // Toccando una voce si va altrove: il pannello si chiude subito, cosi'
    // durante il caricamento della pagina nuova non resta aperto a meta'.
    pannello.querySelectorAll("a").forEach(function (a) {
      a.addEventListener("click", function () { mostra(false); });
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && aperto()) { mostra(false); tasto.focus(); }
    });

    // Ruotando il telefono o allargando la finestra le voci tornano nella
    // barra: il pannello va chiuso, altrimenti resta appeso a meta' pagina
    // e il corpo della pagina resterebbe bloccato.
    if (window.matchMedia) {
      var largo = window.matchMedia("(min-width: 721px)");
      var chiudi = function (m) { if (m.matches) mostra(false); };
      if (largo.addEventListener) largo.addEventListener("change", chiudi);
      else if (largo.addListener) largo.addListener(chiudi);
    }
  });
})();
