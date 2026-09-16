/* Menu del pannello su telefono.
 *
 * Su schermo largo la colonna delle voci sta sempre a sinistra e questo
 * script non tocca niente. Su telefono la colonna diventa un pannello che
 * scende da sotto la barra: undici voci in fila orizzontale, da trascinare
 * di lato per trovare quella giusta, non erano usabili con un pollice.
 *
 * Il pannello e il velo partono con l'attributo hidden. Al primo avvio
 * hidden viene tolto e sostituito dalla classe "pronto": da quel momento
 * comanda il foglio di stile, che puo' animare l'apertura. Se lo script non
 * partisse, hidden resterebbe e il menu non si aprirebbe, ma le voci si
 * raggiungerebbero comunque dalla pagina: niente si rompe.
 *
 * E' gemello di menu.js, quello del sito pubblico. Restano due file perche'
 * i due menu vivono in pagine diverse, con nomi ed elementi propri: unirli
 * avrebbe voluto dire un file che conosce entrambi e serve male tutti e due.
 */
(function () {
  "use strict";

  /* I gruppi del menu che si aprono e si chiudono.
   *
   * Il browser li apre e li chiude da solo: qui si aggiunge solo il
   * ricordo. Senza, ogni cambio di pagina rimetterebbe tutto come stabilito
   * dal server, e chi tiene aperto "Server" per guardare i registri se lo
   * ritroverebbe chiuso a ogni clic.
   *
   * Il gruppo che contiene la pagina aperta resta aperto comunque, anche se
   * l'ultima volta era stato chiuso: e' la pagina in cui ti trovi, e
   * nasconderla vorrebbe dire non farti vedere dove sei.
   */
  function ricordaGruppi() {
    var gruppi = document.querySelectorAll(".menu-gruppo[data-gruppo]");
    if (!gruppi.length) return;
    var memoria = {};
    try {
      memoria = JSON.parse(localStorage.getItem("pc_menu_gruppi") || "{}");
    } catch (e) { memoria = {}; }

    gruppi.forEach(function (g) {
      var nome = g.getAttribute("data-gruppo");
      var contieneLaPagina = !!g.querySelector("a.active");
      if (!contieneLaPagina && Object.prototype.hasOwnProperty.call(memoria, nome)) {
        g.open = !!memoria[nome];
      }
      g.addEventListener("toggle", function () {
        memoria[nome] = g.open;
        try {
          localStorage.setItem("pc_menu_gruppi", JSON.stringify(memoria));
        } catch (e) { /* spazio finito o cronologia privata: pazienza */ }
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    ricordaGruppi();
    var tasto = document.getElementById("adminTasto");
    var pannello = document.getElementById("adminMenu");
    var velo = document.getElementById("adminVelo");
    if (!tasto || !pannello) return;

    if (velo) { velo.hidden = false; velo.classList.add("pronto"); }
    pannello.classList.add("pronto");

    function aperto() { return pannello.classList.contains("aperto"); }

    function mostra(si) {
      pannello.classList.toggle("aperto", si);
      if (velo) velo.classList.toggle("aperto", si);
      tasto.setAttribute("aria-expanded", si ? "true" : "false");
      tasto.classList.toggle("aperto", si);
      document.body.classList.toggle("menu-fermo", si);
    }

    tasto.addEventListener("click", function (e) {
      e.stopPropagation();
      mostra(!aperto());
    });

    if (velo) velo.addEventListener("click", function () { mostra(false); });

    // Toccando una voce si cambia pagina: il pannello si chiude subito,
    // cosi' durante il caricamento non resta aperto a meta'.
    pannello.querySelectorAll("a").forEach(function (a) {
      a.addEventListener("click", function () { mostra(false); });
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && aperto()) { mostra(false); tasto.focus(); }
    });

    // Ruotando il telefono o allargando la finestra la colonna torna al suo
    // posto: il pannello va chiuso, altrimenti il corpo della pagina
    // resterebbe bloccato senza motivo.
    if (window.matchMedia) {
      var largo = window.matchMedia("(min-width: 861px)");
      var chiudi = function (m) { if (m.matches) mostra(false); };
      if (largo.addEventListener) largo.addEventListener("change", chiudi);
      else if (largo.addListener) largo.addListener(chiudi);
    }
  });
})();
