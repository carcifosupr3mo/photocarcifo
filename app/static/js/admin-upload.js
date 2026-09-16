/* Caricamento foto: coda con invii in parallelo e avanzamento per file. */
(function () {
  "use strict";
  var CSRF = "", coda = [], inCorso = 0, fatti = 0, byteTot = 0, byteFatti = 0;
  var PARALLELI = 3;

  document.addEventListener("DOMContentLoaded", function () {
    CSRF = document.getElementById("csrf").value;
    var drop = document.getElementById("drop");
    var picker = document.getElementById("picker");
    var dest = document.getElementById("destSel");

    dest.addEventListener("input", function () {
      var opt = document.querySelector('#destList option[value="' + cssEsc(dest.value) + '"]');
      var id = opt ? opt.getAttribute("data-id") : "";
      document.getElementById("destId").value = id;
      document.getElementById("destEcho").textContent =
        id ? "Destinazione: " + dest.value : "Album non riconosciuto.";
      aggiornaPulsante();
    });

    drop.addEventListener("click", function () { picker.click(); });
    drop.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); picker.click(); }
    });
    picker.addEventListener("change", function () { accoda(picker.files); picker.value = ""; });

    ["dragenter", "dragover"].forEach(function (ev) {
      drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.add("over"); });
    });
    ["dragleave", "drop"].forEach(function (ev) {
      drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.remove("over"); });
    });
    drop.addEventListener("drop", function (e) {
      if (e.dataTransfer && e.dataTransfer.files) accoda(e.dataTransfer.files);
    });

    document.getElementById("btnStart").addEventListener("click", avvia);
    document.getElementById("btnClear").addEventListener("click", svuota);
    document.getElementById("btnScan").addEventListener("click", aggiornaArchivio);
  });

  function cssEsc(s) { return (s || "").replace(/"/g, '\\"'); }

  function accoda(files) {
    Array.prototype.forEach.call(files, function (f) {
      var riga = document.createElement("li");
      riga.className = "up-item";
      riga.innerHTML = "<span class='nome'></span><span class='stato'>in attesa</span>" +
                       "<span class='mini'><i></i></span>";
      riga.querySelector(".nome").textContent = f.name;
      document.getElementById("list").appendChild(riga);
      coda.push({ file: f, riga: riga, stato: "attesa" });
      byteTot += f.size;
    });
    riepilogo();
    aggiornaPulsante();
  }

  function svuota() {
    if (inCorso > 0) { PC.avviso("Attendi la fine del caricamento in corso."); return; }
    coda = []; fatti = 0; byteTot = 0; byteFatti = 0;
    document.getElementById("list").innerHTML = "";
    document.getElementById("barAll").style.width = "0%";
    document.getElementById("doneBox").hidden = true;
    riepilogo(); aggiornaPulsante();
  }

  function aggiornaPulsante() {
    var pronto = coda.some(function (v) { return v.stato === "attesa"; }) &&
                 !!document.getElementById("destId").value;
    document.getElementById("btnStart").disabled = !pronto || inCorso > 0;
  }

  function riepilogo() {
    var attesa = coda.filter(function (v) { return v.stato === "attesa"; }).length;
    var errori = coda.filter(function (v) { return v.stato === "errore"; }).length;
    var testo = coda.length ? (coda.length + " file — " + fatti + " caricati, " +
                attesa + " in attesa") : "Nessun file in coda.";
    if (errori) testo += ", " + errori + " non riusciti";
    document.getElementById("summary").textContent = testo;
  }

  function avvia() {
    document.getElementById("doneBox").hidden = true;
    aggiornaPulsante();
    for (var i = 0; i < PARALLELI; i++) prossimo();
  }

  function prossimo() {
    var v = coda.find(function (x) { return x.stato === "attesa"; });
    if (!v) {
      if (inCorso === 0 && fatti > 0) document.getElementById("doneBox").hidden = false;
      aggiornaPulsante();
      return;
    }
    v.stato = "invio"; inCorso++;
    v.riga.querySelector(".stato").textContent = "invio…";
    invia(v);
  }

  function invia(v) {
    var fd = new FormData();
    fd.append("csrf_token", CSRF);
    fd.append("node_id", document.getElementById("destId").value);
    fd.append("subfolder", document.getElementById("subfolder").value || "");
    fd.append("file", v.file, v.file.name);

    var xhr = new XMLHttpRequest();
    xhr.open("POST", "/admin/upload/file", true);
    var ultimo = 0;
    xhr.upload.onprogress = function (e) {
      if (!e.lengthComputable) return;
      byteFatti += (e.loaded - ultimo); ultimo = e.loaded;
      v.riga.querySelector(".mini i").style.width =
        Math.round(e.loaded / e.total * 100) + "%";
      if (byteTot > 0) {
        document.getElementById("barAll").style.width =
          Math.min(100, Math.round(byteFatti / byteTot * 100)) + "%";
      }
    };
    xhr.onload = function () {
      inCorso--;
      if (xhr.status === 200) {
        v.stato = "fatto"; fatti++;
        v.riga.classList.add("ok");
        v.riga.querySelector(".stato").textContent = "caricato";
      } else {
        v.stato = "errore";
        v.riga.classList.add("ko");
        v.riga.querySelector(".stato").textContent = messaggio(xhr);
      }
      riepilogo(); prossimo();
    };
    xhr.onerror = function () {
      inCorso--; v.stato = "errore";
      v.riga.classList.add("ko");
      v.riga.querySelector(".stato").textContent = "connessione interrotta";
      riepilogo(); prossimo();
    };
    xhr.send(fd);
  }

  function messaggio(xhr) {
    try {
      var d = JSON.parse(xhr.responseText);
      if (d && d.detail) return d.detail;
    } catch (e) {}
    return "errore " + xhr.status;
  }

  function aggiornaArchivio() {
    var eco = document.getElementById("scanEcho");
    eco.textContent = "Lettura in corso…";
    var fd = new FormData();
    fd.append("csrf_token", CSRF);
    fetch("/admin/upload/rescan", { method: "POST", body: fd })
      .then(function (r) { return r.json(); })
      .then(function () {
        eco.textContent = "Archivio in aggiornamento: le foto compariranno tra poco.";
      })
      .catch(function () { eco.textContent = "Aggiornamento non riuscito."; });
  }
})();
