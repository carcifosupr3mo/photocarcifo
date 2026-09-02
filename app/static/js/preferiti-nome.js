/* Chiede chi sta scegliendo le fotografie, una volta per sessione. */
(function () {
  "use strict";

  /* Mette in forma neutra i caratteri che avrebbero significato dentro il
     formato della pagina. Le scritte tradotte contengono apostrofi e
     virgolette: senza questo passaggio romperebbero il riquadro. */
  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  var inSospeso = null;
  var CHIAVE = "pc_nome_sessione";

  function giaChiesto() {
    try { return sessionStorage.getItem(CHIAVE) === "1"; } catch (e) { return false; }
  }
  function segnaChiesto() {
    try { sessionStorage.setItem(CHIAVE, "1"); } catch (e) {}
  }

  function pulisciIg(v) {
    v = (v || "").trim();
    v = v.replace(/^https?:\/\/(www\.)?instagram\.com\//i, "");
    return v.split("?")[0].replace(/^[@\/]+|[\/\s]+$/g, "").trim();
  }
  function validoIg(n) {
    if (!n || n.length > 30) return false;
    if (n.indexOf("..") !== -1) return false;
    if (n.charAt(0) === "." || n.charAt(n.length - 1) === ".") return false;
    return /^[A-Za-z0-9._]+$/.test(n);
  }
  function validoNome(n) {
    n = (n || "").trim();
    return n.length >= 2 && n.length <= 60 && /^[A-Za-zÀ-ÿ' ]+$/.test(n);
  }

  window.preferitiRichiediNome = function (prosegui) {
    if (giaChiesto()) { prosegui(); return; }
    inSospeso = prosegui;
    apri();
  };

  function apri() {
    if (document.getElementById("nomeBox")) return;
    var d = document.createElement("div");
    d.className = "nome-overlay";
    d.id = "nomeBox";
    d.innerHTML =
      "<div class='nome-card' role='dialog' aria-modal='true' aria-labelledby='nomeT'>" +
      "<h3 id='nomeT'>" + esc(T("nome_titolo")) + "</h3>" +
      "<p>" + esc(T("nome_sotto")) + "</p>" +
      "<div class='nome-tab'>" +
      "<button type='button' class='attivo' data-modo='ig'>Instagram</button>" +
      "<button type='button' data-modo='nome'>" + esc(T("nome_cognome")) + "</button>" +
      "</div>" +
      "<div id='campoIg'><div class='nome-campo'><span>@</span>" +
      "<input type='text' id='nomeIg' placeholder='" + esc(T("nome_ph_ig")) + "' autocomplete='off' " +
      "autocapitalize='off' spellcheck='false'></div></div>" +
      "<div id='campoNome' hidden><div class='nome-campo'>" +
      "<input type='text' id='nomePers' placeholder='" + esc(T("nome_ph_nome")) + "' " +
      "autocomplete='name' style='padding-left:.9rem;'></div></div>" +
      "<p class='nome-errore' id='nomeErr' hidden></p>" +
      "<div class='nome-azioni'>" +
      "<button class='btn btn-accent' id='nomeOk' type='button'>" + esc(T("nome_continua")) + "</button>" +
      "</div></div>";
    document.body.appendChild(d);
    document.body.style.overflow = "hidden";
    document.getElementById("nomeIg").focus();

    d.querySelectorAll("[data-modo]").forEach(function (b) {
      b.addEventListener("click", function () {
        var modo = b.getAttribute("data-modo");
        d.querySelectorAll("[data-modo]").forEach(function (x) {
          x.classList.toggle("attivo", x === b);
        });
        document.getElementById("campoIg").hidden = (modo !== "ig");
        document.getElementById("campoNome").hidden = (modo !== "nome");
        document.getElementById("nomeErr").hidden = true;
        document.getElementById(modo === "ig" ? "nomeIg" : "nomePers").focus();
      });
    });

    ["nomeIg", "nomePers"].forEach(function (id) {
      document.getElementById(id).addEventListener("keydown", function (e) {
        if (e.key === "Enter") { e.preventDefault(); conferma(); }
      });
    });
    document.getElementById("nomeOk").addEventListener("click", conferma);
  }

  /* Aggiorna subito il pulsante in alto, senza ricaricare la pagina. */
  function aggiornaNav(valore) {
    var v = valore;
    if (!v) {
      var m = document.cookie.match(/(?:^|;\s*)pc_nome=([^;]+)/);
      v = m ? decodeURIComponent(m[1]) : "";
    }
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

  function chiudi() {
    var d = document.getElementById("nomeBox");
    if (d) d.remove();
    document.body.style.overflow = "";
  }

  function errore(t) {
    var e = document.getElementById("nomeErr");
    e.textContent = t; e.hidden = false;
  }

  function conferma() {
    var usaIg = !document.getElementById("campoIg").hidden;
    var fd = new FormData();
    if (usaIg) {
      var n = pulisciIg(document.getElementById("nomeIg").value);
      if (!n) { errore(T("nome_err_ig")); return; }
      if (!validoIg(n)) {
        errore(T("nome_err_ig2"));
        return;
      }
      fd.append("tipo", "ig");
      fd.append("instagram", n);
    } else {
      var p = document.getElementById("nomePers").value.trim();
      if (!validoNome(p)) { errore(T("nome_err_nome")); return; }
      fd.append("tipo", "nome");
      fd.append("nome_persona", p);
    }
    var b = document.getElementById("nomeOk");
    b.disabled = true; b.textContent = T("nome_attimo");
    fetch("/preferiti-nome", { method: "POST", body: fd })
      .then(function (r) {
        if (!r.ok) return r.json().then(function (d) { throw new Error(d.detail || "errore"); });
        return r.json();
      })
      .then(function (d) {
        segnaChiesto();
        chiudi();
        aggiornaNav(d && d.instagram ? d.instagram : "");
        if (inSospeso) { var f = inSospeso; inSospeso = null; f(); }
      })
      .catch(function (e) {
        errore(e.message || T("nome_ko"));
        b.disabled = false; b.textContent = T("nome_continua");
      });
  }
})();
