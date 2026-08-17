/* Avvisi brevi in fondo allo schermo.
 *
 * Serve a colmare un vuoto preciso: quando una richiesta al server non
 * andava a buon fine, il pulsante tornava semplicemente com'era. Nessuna
 * spiegazione, nessuna traccia. Chi guardava premeva di nuovo, credendo di
 * aver sbagliato mira, e il sito sembrava rotto senza dire perche'.
 *
 * Si usa cosi', da qualunque altro script:
 *
 *     PC.avviso("Non riesco a salvare");            // errore, rosso
 *     PC.avviso("Salvato", "ok");                   // conferma, verde
 *
 * L'avviso viene letto anche dai lettori di schermo: gli errori come
 * "alert", cioe' subito, le conferme come "status", cioe' quando c'e' una
 * pausa. Senza questa distinzione un errore verrebbe annunciato in ritardo,
 * quando ormai la persona ha gia' fatto altro.
 */
(function () {
  "use strict";
  window.PC = window.PC || {};

  var DURATA = 6000;      // quanto resta a schermo prima di sparire
  var contenitore = null;

  function scritta(chiave, ripiego) {
    // T() esiste solo sulle pagine pubbliche: nel pannello si usa il
    // ripiego in italiano, che li' e' l'unica lingua.
    return (typeof window.T === "function") ? window.T(chiave) : ripiego;
  }

  function prepara() {
    if (contenitore) return contenitore;
    contenitore = document.createElement("div");
    contenitore.className = "avvisi";
    document.body.appendChild(contenitore);
    return contenitore;
  }

  PC.avviso = function (testo, tipo) {
    if (!testo) return;
    var zona = prepara();
    var a = document.createElement("div");
    a.className = "avviso avviso-" + (tipo === "ok" ? "ok" : "errore");
    a.setAttribute("role", tipo === "ok" ? "status" : "alert");
    a.setAttribute("aria-live", tipo === "ok" ? "polite" : "assertive");

    var p = document.createElement("p");
    p.textContent = testo;
    a.appendChild(p);

    var chiudi = document.createElement("button");
    chiudi.type = "button";
    chiudi.className = "avviso-chiudi";
    chiudi.setAttribute("aria-label", scritta("avviso_chiudi", "Chiudi l'avviso"));
    chiudi.innerHTML = "<svg viewBox='0 0 14 14' aria-hidden='true'>" +
      "<path d='M2 2l10 10M12 2L2 12'/></svg>";
    chiudi.addEventListener("click", function () { via(a); });
    a.appendChild(chiudi);

    zona.appendChild(a);
    requestAnimationFrame(function () { a.classList.add("visibile"); });
    setTimeout(function () { via(a); }, DURATA);
  };

  /* Scorciatoia per il caso piu' frequente: una richiesta non riuscita. */
  PC.avvisoRete = function () {
    PC.avviso(scritta("rete_ko",
      "Non e' stato possibile completare l'operazione. " +
      "Controlla la connessione e riprova."));
  };

  function via(a) {
    if (!a || !a.parentNode) return;
    a.classList.remove("visibile");
    // Si toglie dal documento solo a dissolvenza finita, altrimenti
    // sparirebbe di scatto.
    setTimeout(function () {
      if (a.parentNode) a.parentNode.removeChild(a);
    }, 250);
  }
})();
