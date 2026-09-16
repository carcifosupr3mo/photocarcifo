/* Scritte del sito nella lingua scelta, per gli script.
 *
 * Il server le consegna gia' tradotte in un blocco di dati dentro la pagina.
 * Qui si leggono una volta sola e si mettono a disposizione con T("chiave").
 * Va caricato senza "defer": gli altri script lo usano appena partono.
 *
 * T accetta dei segnaposto: T("sel_scarica", {n: 3}) sostituisce {n} con 3.
 * Se una chiave manca si restituisce la chiave stessa, cosi' la mancanza si
 * vede subito invece di lasciare un pulsante vuoto.
 */
(function () {
  "use strict";
  var voci = {};
  try {
    var blocco = document.getElementById("pcTesti");
    if (blocco) voci = JSON.parse(blocco.textContent) || {};
  } catch (e) { voci = {}; }

  window.T = function (chiave, valori) {
    var testo = voci[chiave];
    if (testo === undefined) return chiave;
    if (!valori) return testo;
    return testo.replace(/\{(\w+)\}/g, function (intero, nome) {
      return valori[nome] !== undefined ? valori[nome] : intero;
    });
  };
})();
