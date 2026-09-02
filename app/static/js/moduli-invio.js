/* Stato "invio in corso" sui moduli pubblici (contattami, recensioni):
   disabilita il pulsante e aggiunge .in-attesa (la stessa classe gia' usata
   altrove nel sito, vedi app.js) appena il modulo viene inviato davvero.

   "Davvero" e' la parte delicata. Questi moduli usano i campi required di
   HTML, controllati dal browser PRIMA che l'evento submit scatti: se manca
   l'email, il browser blocca l'invio e mostra il suo avviso, ma se qui si
   disabilitasse il pulsante comunque, l'unico modo di inviare il modulo
   sarebbe ricaricare la pagina. Per questo il pulsante si disabilita
   nell'evento submit stesso (che il browser fa scattare solo se i campi
   sono validi) e non, per esempio, al click sul pulsante.

   Non c'e' bisogno di "riabilitare" niente dopo: e' un invio POST
   tradizionale, non una richiesta fetch. O il modulo va a buon fine e la
   pagina cambia (redirect a ?inviato=1), o il server risponde con un
   errore e la pagina si ricarica comunque con il modulo di nuovo pronto —
   in entrambi i casi il vecchio pulsante disabilitato sparisce con la
   pagina che lo conteneva. */
(function () {
  "use strict";
  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("form[data-invio-unico]").forEach(function (modulo) {
      modulo.addEventListener("submit", function () {
        var bottone = modulo.querySelector('button[type="submit"]');
        if (!bottone || bottone.disabled) return;
        bottone.disabled = true;
        bottone.classList.add("in-attesa");
      });
    });
  });
})();
