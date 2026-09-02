document.addEventListener("DOMContentLoaded", function () {
  var csrf = document.getElementById("csrf").value;

  function revoca(url, riga, messaggio) {
    if (!confirm(messaggio)) return;
    var fd = new FormData();
    fd.append("csrf_token", csrf);
    fetch(url, { method: "POST", body: fd })
      .then(function (r) { if (!r.ok) throw new Error(); return r.json(); })
      .then(function () {
        if (riga) riga.remove();
        PC.avviso("Link revocato.");
      })
      .catch(function () { PC.avviso("Revoca non riuscita."); });
  }

  document.querySelectorAll("[data-revoca-singola]").forEach(function (b) {
    b.addEventListener("click", function () {
      var id = b.getAttribute("data-revoca-singola");
      var riga = document.querySelector("[data-riga-singola='" + id + "']");
      revoca("/admin/tree/media/" + id + "/share/revoke", riga,
        "Revocare il link di questa fotografia? Chi lo ha ricevuto non potrà più aprirlo.");
    });
  });

  document.querySelectorAll("[data-revoca-selezione]").forEach(function (b) {
    b.addEventListener("click", function () {
      var id = b.getAttribute("data-revoca-selezione");
      var riga = document.querySelector("[data-riga-selezione='" + id + "']");
      revoca("/admin/tree/condivisioni/" + id + "/revoca", riga,
        "Revocare il link di questa selezione? Chi lo ha ricevuto non potrà più aprirla.");
    });
  });

  document.querySelectorAll("[data-copia-link]").forEach(function (b) {
    b.addEventListener("click", function () {
      var url = b.getAttribute("data-copia-link");
      function fatto() { PC.avviso("Link copiato."); }
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(url).then(fatto).catch(function () {
          window.prompt("Link di condivisione:", url);
        });
      } else {
        window.prompt("Link di condivisione:", url);
      }
    });
  });
});
