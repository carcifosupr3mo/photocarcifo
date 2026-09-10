/* Banner di supporto volontario: si mostra una volta per sessione del
   browser (sessionStorage, non cookie), a differenza dell'avviso cookie
   che resta accettato per un anno. Stessa struttura di cookie-avviso.js. */
(function () {
  "use strict";
  var CHIAVE = "pc_supporto_visto";

  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function gia_visto() {
    try { return sessionStorage.getItem(CHIAVE) === "1"; }
    catch (e) { return false; }  // sessionStorage puo' non essere disponibile (privacy mode)
  }

  function ricorda() {
    try { sessionStorage.setItem(CHIAVE, "1"); } catch (e) {}
  }

  // Stessa posizione fissa in basso del banner cookie (.cookie-avviso):
  // se quello non e' ancora stato accettato, i due si sovrapporrebbero
  // nello stesso punto dello schermo. Si aspetta semplicemente il
  // prossimo caricamento pagina, quando il banner cookie non c'e' piu'
  // (accettato) o e' gia' stato deciso in precedenza - nessuno stacking
  // verticale complesso, un solo banner alla volta in quella posizione.
  function cookie_non_deciso() {
    return document.cookie.indexOf("pc_cookie_ok=1") === -1;
  }

  function copia(testo, bottone) {
    function mostraCopiato() {
      var originale = bottone.textContent;
      bottone.textContent = T("supporto_copiato");
      bottone.classList.add("ok");
      setTimeout(function () {
        bottone.textContent = originale;
        bottone.classList.remove("ok");
      }, 1500);
    }
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(testo).then(mostraCopiato, function () {
        window.prompt(T("supporto_copia_manuale"), testo);
      });
    } else {
      window.prompt(T("supporto_copia_manuale"), testo);
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    if (gia_visto() || cookie_non_deciso()) return;

    var datiEl = document.getElementById("pcSupporto");
    var dati = {};
    try { dati = JSON.parse(datiEl.textContent); } catch (e) {}
    if (!dati.twint && !dati.iban) return;  // niente configurato, niente banner

    var d = document.createElement("div");
    d.className = "cookie-avviso supporto-avviso";
    d.setAttribute("role", "region");
    d.setAttribute("aria-label", T("supporto_aria"));

    var righeContatto = "";
    if (dati.twint) {
      righeContatto += "<div class='supporto-contatto'><span>" + T("supporto_twint_label") +
        ": <strong>" + esc(dati.twint) + "</strong></span>" +
        "<button class='btn btn-ghost btn-sm' type='button' data-copia='twint'>" +
        esc(T("supporto_copia")) + "</button></div>";
    }
    if (dati.iban) {
      righeContatto += "<div class='supporto-contatto'><span>" + T("supporto_iban_label") +
        ": <strong>" + esc(dati.iban) + "</strong></span>" +
        "<button class='btn btn-ghost btn-sm' type='button' data-copia='iban'>" +
        esc(T("supporto_copia")) + "</button></div>";
    }
    if (dati.twint || dati.iban) {
      righeContatto += "<div class='supporto-contatto'><span>" + T("supporto_causale_label") +
        ": <strong>" + esc(T("supporto_causale_valore")) + "</strong></span>" +
        "<button class='btn btn-ghost btn-sm' type='button' data-copia='causale'>" +
        esc(T("supporto_copia")) + "</button></div>";
    }

    d.innerHTML =
      "<div class='cookie-testo'>" +
      "<strong>" + esc(T("supporto_titolo")) + "</strong> " +
      esc(T("supporto_testo")) +
      "<div class='supporto-contatti'>" + righeContatto + "</div>" +
      "</div>" +
      "<div class='cookie-azioni'>" +
      "<button class='btn btn-accent' type='button' data-chiudi>" + esc(T("supporto_chiudi")) + "</button>" +
      "</div>";
    document.body.appendChild(d);
    requestAnimationFrame(function () { d.classList.add("visibile"); });

    d.querySelectorAll("[data-copia]").forEach(function (b) {
      b.addEventListener("click", function () {
        var chiave = b.getAttribute("data-copia");
        var valore = chiave === "twint" ? dati.twint :
          chiave === "iban" ? dati.iban : T("supporto_causale_valore");
        copia(valore, b);
      });
    });
    d.querySelector("[data-chiudi]").addEventListener("click", function () {
      ricorda();
      d.classList.remove("visibile");
      setTimeout(function () { d.remove(); }, 300);
    });
  });
})();
