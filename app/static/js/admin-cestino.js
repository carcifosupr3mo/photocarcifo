document.addEventListener("DOMContentLoaded", function () {
  var csrf = document.getElementById("csrf").value;
  document.querySelectorAll("[data-lotto]").forEach(function (b) {
    b.addEventListener("click", function () {
      if (!confirm("Rimettere a posto tutti i file di questo gruppo?")) return;
      b.disabled = true; b.textContent = "Ripristino…";
      var fd = new FormData();
      fd.append("csrf_token", csrf);
      fd.append("lotto", b.getAttribute("data-lotto"));
      fetch("/admin/trash/restore", { method: "POST", body: fd })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          PC.avviso("Ripristinati " + d.ripristinati + " file. Aggiorna l'archivio da Carica foto per rivederli sul sito.");
          location.reload();
        })
        .catch(function () { PC.avviso("Ripristino non riuscito."); b.disabled = false; });
    });
  });
});