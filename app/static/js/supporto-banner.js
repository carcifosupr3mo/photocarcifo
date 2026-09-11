/* Popup di supporto volontario: modal centrale (non un bottom-bar come il
   banner cookie), mostrato una volta per sessione del browser
   (sessionStorage, non cookie: deve poter tornare a ogni nuova sessione,
   niente "non mostrare piu'"). Riusa lo stesso linguaggio visivo del
   pannello di condivisione (.share-panel/.share-panel-card in style.css),
   non uno stile nuovo. */
(function () {
  "use strict";
  var CHIAVE = "pc_supporto_visto";

  function gia_visto() {
    try { return sessionStorage.getItem(CHIAVE) === "1"; }
    catch (e) { return false; }  // sessionStorage puo' non essere disponibile (privacy mode)
  }

  function ricorda() {
    try { sessionStorage.setItem(CHIAVE, "1"); } catch (e) {}
  }

  function cookie_accettato() {
    return document.cookie.indexOf("pc_cookie_ok=1") !== -1;
  }

  function mostraPopup() {
    if (gia_visto()) return;

    var datiEl = document.getElementById("pcSupporto");
    var dati = {};
    try { dati = JSON.parse(datiEl.textContent); } catch (e) {}
    if (!dati.twint && !dati.iban) return;  // niente configurato, niente popup

    var attivoPrima = document.activeElement;

    var fondo = document.createElement("div");
    fondo.className = "share-panel";

    var scatola = document.createElement("div");
    scatola.className = "share-panel-card";
    scatola.setAttribute("role", "dialog");
    scatola.setAttribute("aria-modal", "true");
    scatola.setAttribute("aria-labelledby", "supportoTitolo");

    var testa = document.createElement("div");
    testa.className = "share-panel-head";
    var titolo = document.createElement("strong");
    titolo.id = "supportoTitolo";
    titolo.textContent = T("supporto_titolo");
    var chiudiBtn = document.createElement("button");
    chiudiBtn.type = "button";
    chiudiBtn.className = "share-panel-close";
    chiudiBtn.innerHTML = "&times;";
    chiudiBtn.setAttribute("aria-label", T("supporto_chiudi"));
    testa.appendChild(titolo);
    testa.appendChild(chiudiBtn);

    var corpo = document.createElement("div");
    corpo.className = "supporto-corpo";

    var testo = document.createElement("p");
    testo.className = "supporto-testo";
    testo.textContent = T("supporto_testo");

    var righe = document.createElement("div");
    righe.className = "supporto-righe";

    function riga(etichetta, valore, cliccabile, dataCopia) {
      var r = document.createElement("div");
      r.className = "supporto-riga";
      var lab = document.createElement("span");
      lab.className = "supporto-etichetta";
      lab.textContent = etichetta;
      var val = document.createElement(cliccabile ? "button" : "span");
      val.className = cliccabile ? "supporto-valore supporto-valore-clic" : "supporto-valore";
      if (cliccabile) {
        val.type = "button";
        val.setAttribute("data-copia", dataCopia);
        val.setAttribute("aria-label", etichetta + ", " + T("supporto_copia_aria"));
      }
      val.textContent = valore;
      r.appendChild(lab);
      r.appendChild(val);
      righe.appendChild(r);
      return val;
    }

    if (dati.twint) riga(T("supporto_twint_label"), dati.twint, true, "twint");
    if (dati.iban) riga(T("supporto_iban_label"), dati.iban, true, "iban");
    if (dati.twint || dati.iban) {
      riga(T("supporto_causale_label"), T("supporto_causale_valore"), false, null);
    }

    var grazie = document.createElement("p");
    grazie.className = "supporto-grazie";
    grazie.textContent = T("supporto_chiudi_frase");

    corpo.appendChild(testo);
    corpo.appendChild(righe);
    corpo.appendChild(grazie);
    scatola.appendChild(testa);
    scatola.appendChild(corpo);
    fondo.appendChild(scatola);

    function chiudi() {
      if (!fondo.parentNode) return;
      ricorda();
      document.removeEventListener("keydown", tasto);
      fondo.parentNode.removeChild(fondo);
      if (attivoPrima && attivoPrima.focus) attivoPrima.focus();
    }
    function tasto(e) {
      if (e.key !== "Escape") return;
      e.preventDefault();
      chiudi();
    }
    fondo.addEventListener("click", function (e) {
      if (e.target === fondo) chiudi();
    });
    chiudiBtn.addEventListener("click", chiudi);
    document.addEventListener("keydown", tasto);

    // Nuvoletta discreta "IBAN copiato" / "Numero copiato": non alert(),
    // non sposta il layout (position:absolute rispetto alla riga), sparisce
    // da sola dopo un paio di secondi.
    function mostraNuvoletta(elemento, messaggio) {
      var precedente = elemento.parentNode.querySelector(".supporto-nuvoletta");
      if (precedente) precedente.remove();
      var nuv = document.createElement("span");
      nuv.className = "supporto-nuvoletta";
      nuv.textContent = messaggio;
      nuv.setAttribute("role", "status");
      elemento.parentNode.appendChild(nuv);
      requestAnimationFrame(function () { nuv.classList.add("visibile"); });
      setTimeout(function () {
        nuv.classList.remove("visibile");
        setTimeout(function () { nuv.remove(); }, 200);
      }, 1600);
    }

    function copia(testoDaCopiare, elemento, messaggio) {
      function fatto() { mostraNuvoletta(elemento, messaggio); }
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(testoDaCopiare).then(fatto, fatto);
      } else {
        // Fallback minimo senza prompt/alert: un campo temporaneo,
        // selezionato e copiato con l'API storica execCommand.
        var campo = document.createElement("textarea");
        campo.value = testoDaCopiare;
        campo.style.position = "fixed";
        campo.style.opacity = "0";
        document.body.appendChild(campo);
        campo.select();
        try { document.execCommand("copy"); } catch (e) {}
        document.body.removeChild(campo);
        fatto();
      }
    }

    scatola.querySelectorAll("[data-copia]").forEach(function (b) {
      b.addEventListener("click", function () {
        var chiave = b.getAttribute("data-copia");
        var valore = chiave === "twint" ? dati.twint : dati.iban;
        var messaggio = chiave === "twint" ? T("supporto_twint_copiato") : T("supporto_iban_copiato");
        copia(valore, b, messaggio);
      });
    });

    document.body.appendChild(fondo);
    requestAnimationFrame(function () {
      fondo.classList.add("open");
      chiudiBtn.focus();
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    if (gia_visto()) return;

    if (cookie_accettato()) {
      mostraPopup();
      return;
    }

    // Il banner cookie non e' ancora stato accettato: si aspetta il suo
    // click reale (nessun timeout indovinato). cookie-avviso.js genera un
    // unico bottone dentro .cookie-avviso .cookie-azioni; qui si intercetta
    // quel click in fase di cattura, PRIMA che il suo stesso handler lo
    // rimuova dal DOM, cosi' il popup di supporto arriva un istante dopo,
    // mai insieme.
    document.addEventListener("click", function attendiCookie(e) {
      var bottoneCookie = e.target.closest &&
        e.target.closest(".cookie-avviso .cookie-azioni button");
      if (!bottoneCookie) return;
      document.removeEventListener("click", attendiCookie, true);
      setTimeout(mostraPopup, 350);  // dopo la transizione di chiusura del banner cookie (320ms)
    }, true);
  });
})();
