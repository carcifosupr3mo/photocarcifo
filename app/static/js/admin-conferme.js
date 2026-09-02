/* Conferme prima di inviare un modulo del pannello.

   La Content-Security-Policy del sito vieta gli script scritti dentro la
   pagina, quindi un attributo onsubmit="confirm(...)" verrebbe bloccato dal
   browser e il modulo partirebbe senza chiedere niente. La conferma si
   aggancia da qui, con <form data-conferma="Testo della domanda">.
*/
(function () {
  "use strict";
  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("form[data-conferma]").forEach(function (modulo) {
      modulo.addEventListener("submit", function (evento) {
        if (!window.confirm(modulo.getAttribute("data-conferma"))) {
          evento.preventDefault();
        }
      });
    });
  });
})();
