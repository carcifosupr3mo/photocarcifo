/* Avviso iniziale: si mostra una volta sola e resta accettato per un anno. */
(function () {
  "use strict";
  var CHIAVE = "pc_cookie_ok";

  /* Mette in forma neutra i caratteri che avrebbero significato dentro il
     formato della pagina. Le scritte tradotte contengono apostrofi e
     virgolette: senza questo passaggio romperebbero il riquadro. */
  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function accettato() {
    return document.cookie.indexOf(CHIAVE + "=1") !== -1;
  }

  function ricorda() {
    var anno = 60 * 60 * 24 * 365;
    document.cookie = CHIAVE + "=1; path=/; max-age=" + anno + "; samesite=lax; secure";
  }

  document.addEventListener("DOMContentLoaded", function () {
    if (accettato() || location.pathname === "/privacy") return;

    // Le condizioni esistono in cinque lingue, una per indirizzo. Questo
    // riquadro nasce dal browser, quindi non passa dalla riscrittura dei
    // collegamenti fatta dal server: il pezzo di lingua se lo legge da solo
    // dall'indirizzo della pagina in cui si trova.
    function prefissoLingua() {
      var m = location.pathname.match(/^\/(en|fr|de|es)(\/|$)/);
      return m ? "/" + m[1] : "";
    }

    var d = document.createElement("div");
    d.className = "cookie-avviso";
    d.setAttribute("role", "region");
    d.setAttribute("aria-label", T("cookie_aria"));
    d.innerHTML =
      "<div class='cookie-testo'>" +
      "<strong>" + esc(T("cookie_forte")) + "</strong> " +
      esc(T("cookie_testo")).replace("@photocarcifo", "<strong>@photocarcifo</strong>") +
      "</div>" +
      "<div class='cookie-azioni'>" +
      "<a class='btn btn-ghost' href='" + prefissoLingua() + "/privacy'>" + esc(T("cookie_leggi")) + "</a>" +
      "<button class='btn btn-accent' type='button'>" + esc(T("cookie_ok")) + "</button>" +
      "</div>";
    document.body.appendChild(d);
    requestAnimationFrame(function () { d.classList.add("visibile"); });

    d.querySelector("button").addEventListener("click", function () {
      ricorda();
      d.classList.remove("visibile");
      setTimeout(function () { d.remove(); }, 300);
    });
  });
})();
