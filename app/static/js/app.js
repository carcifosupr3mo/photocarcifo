/* Photocarcifo - caricamento progressivo, visualizzatore, selezione multipla.

   La selezione sopravvive al cambio pagina: gli identificativi restano in
   sessionStorage, cosi' su un album da mille foto si possono scegliere
   immagini sparse su piu' pagine e scaricarle in un colpo solo.
*/
(function () {
  "use strict";

  var selecting = false, grid = null, items = [];
  var btnMode, btnDl, btnCancel, btnDel;
  var CHIAVE = "pc_sel_" + (document.body.getAttribute("data-node") || location.pathname);

  function leggiSel() {
    try {
      var v = sessionStorage.getItem(CHIAVE);
      return v ? JSON.parse(v) : [];
    } catch (e) { return []; }
  }
  function scriviSel(ids) {
    try { sessionStorage.setItem(CHIAVE, JSON.stringify(ids)); } catch (e) {}
  }
  function selIds() { return leggiSel(); }
  function isSel(id) { return leggiSel().indexOf(String(id)) !== -1; }
  function toggleId(id) {
    var ids = leggiSel(), i = ids.indexOf(String(id));
    if (i === -1) ids.push(String(id)); else ids.splice(i, 1);
    scriviSel(ids);
    return i === -1;
  }
  function azzeraSel() { try { sessionStorage.removeItem(CHIAVE); } catch (e) {} }

  function initLazyLoad() {
    // Le immagini che il server consegna gia' con il proprio indirizzo (la
    // prima di ogni album, per farla arrivare prima delle altre) non hanno
    // data-src e non passano di qui: gli si applica subito la versione ad
    // alta densita', che altrimenti non userebbero mai.
    Array.prototype.forEach.call(
      document.querySelectorAll("img[data-srcset]:not([data-src])"),
      function (img) {
        img.srcset = img.getAttribute("data-srcset");
        img.removeAttribute("data-srcset");
      });

    var imgs = document.querySelectorAll("img[data-src]");
    if (!("IntersectionObserver" in window)) {
      Array.prototype.forEach.call(imgs, loadImg);
      return;
    }
    var io = new IntersectionObserver(function (es, obs) {
      es.forEach(function (e) {
        if (e.isIntersecting) { loadImg(e.target); obs.unobserve(e.target); }
      });
    }, { rootMargin: "400px 0px", threshold: 0.01 });
    Array.prototype.forEach.call(imgs, function (img) { io.observe(img); });
  }

  function loadImg(img) {
    var src = img.getAttribute("data-src");
    if (!src) return;
    var set = img.getAttribute("data-srcset");
    if (set) { img.srcset = set; img.removeAttribute("data-srcset"); }
    // data-src si toglie a immagine arrivata, non prima: e' la sua assenza
    // che fa comparire la fotografia in dissolvenza. Va tolto anche in caso
    // di errore, altrimenti una miniatura che non si carica lascerebbe un
    // riquadro trasparente per sempre invece del testo alternativo.
    var svela = function () { img.removeAttribute("data-src"); };
    img.addEventListener("load", svela, { once: true });
    img.addEventListener("error", svela, { once: true });
    img.src = src;
    // Se era gia' in memoria, "load" puo' essere passato prima che ci
    // mettessimo in ascolto.
    if (img.complete) svela();
  }

  function refreshBar() {
    var n = selIds().length;
    if (btnDl) {
      btnDl.textContent = T("sel_scarica", {n: n});
      btnDl.disabled = n === 0;
      btnDl.style.opacity = n === 0 ? ".5" : "1";
    }
    if (btnDel) {
      btnDel.textContent = n ? T("sel_rimuovi_n", {n: n}) : T("sel_rimuovi");
      btnDel.disabled = n === 0;
      btnDel.style.opacity = n === 0 ? ".5" : "1";
    }
    var eco = document.getElementById("selEcho");
    if (eco) {
      eco.textContent = n ? T("sel_eco", {n: n}) : "";
      eco.style.display = n ? "block" : "none";
    }
  }

  function segna(item, attivo) {
    item.classList.toggle("selected", attivo);
    var box = item.querySelector(".sel-box");
    if (box) box.setAttribute("aria-checked", attivo ? "true" : "false");
  }

  function toggle(item) {
    var id = item.getAttribute("data-id");
    if (!id) return;
    segna(item, toggleId(id));
    refreshBar();
  }

  function enterSelect() {
    selecting = true;
    document.body.classList.add("selecting");
    btnMode.style.display = "none";
    if (btnDl) btnDl.style.display = "inline-flex";
    if (btnDel) btnDel.style.display = "inline-flex";
    btnCancel.style.display = "inline-flex";
    refreshBar();
  }

  function exitSelect() {
    selecting = false;
    azzeraSel();
    document.body.classList.remove("selecting");
    items.forEach(function (it) { segna(it, false); });
    btnMode.style.display = "inline-flex";
    if (btnDl) btnDl.style.display = "none";
    if (btnDel) btnDel.style.display = "none";
    btnCancel.style.display = "none";
    refreshBar();
  }

  function initGrid() {
    grid = document.querySelector(".photo-grid");
    if (!grid) return;
    items = Array.prototype.slice.call(grid.querySelectorAll(".photo"));
    if (!items.length) return;

    btnMode = document.getElementById("selMode");
    btnDl = document.getElementById("dlSel");
    btnCancel = document.getElementById("selCancel");
    btnDel = document.getElementById("delSel");

    items.forEach(function (it) {
      var id = it.getAttribute("data-id");
      if (!id) return;
      var box = document.createElement("span");
      box.className = "sel-box";
      box.setAttribute("role", "checkbox");
      box.setAttribute("aria-checked", "false");
      box.setAttribute("aria-label", T("sel_questa"));
      box.addEventListener("click", function (e) {
        e.preventDefault(); e.stopPropagation();
        if (!selecting) enterSelect();
        toggle(it);
      });
      it.appendChild(box);
      if (isSel(id)) segna(it, true);
    });

    if (selIds().length && btnMode) enterSelect();

    if (btnMode && btnCancel) {
      btnMode.addEventListener("click", function (e) { e.preventDefault(); enterSelect(); });
      btnCancel.addEventListener("click", function (e) { e.preventDefault(); exitSelect(); });
      if (btnDl) btnDl.addEventListener("click", function (e) {
        e.preventDefault();
        var ids = selIds();
        if (!ids.length) return;
        window.location.href = "/zip/select?ids=" + ids.join(",");
      });
      if (btnDel) btnDel.addEventListener("click", function (e) {
        e.preventDefault(); rimuovi(selIds());
      });
      refreshBar();
    }

    initLightbox();
  }

  function rimuovi(ids) {
    if (!ids.length) return;
    var campo = document.getElementById("csrf");
    if (!campo) { PC.avviso(T("sessione")); return; }
    var testo = ids.length === 1 ? T("cestino_una")
              : T("cestino_n", {n: ids.length});
    if (!confirm(testo + "\n\n" + T("cestino_nota"))) return;
    btnDel.disabled = true; btnDel.textContent = T("rimozione");
    var fd = new FormData();
    fd.append("csrf_token", campo.value);
    fd.append("ids", ids.join(","));
    fetch("/admin/trash/media", { method: "POST", body: fd })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d && d.ok) { azzeraSel(); location.reload(); }
        else { PC.avviso(T("rimozione_ko")); btnDel.disabled = false; }
      })
      .catch(function () { PC.avviso(T("rimozione_ko")); btnDel.disabled = false; });
  }

  function initLightbox() {
    var current = 0;
    var lb = build();
    document.body.appendChild(lb.root);

    items.forEach(function (it, i) {
      it.setAttribute("tabindex", "0");
      it.setAttribute("role", "button");
      it.addEventListener("click", function (ev) {
        if (ev.target.classList.contains("sel-box")) return;
        // Nei risultati di ricerca ogni foto porta il collegamento alla
        // propria cartella: cliccandolo si apre la cartella, non il
        // visualizzatore.
        if (ev.target.closest("a")) return;
        ev.preventDefault();
        if (selecting) { toggle(it); return; }
        open(i);
      });
      it.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); it.click(); }
      });
    });

    function open(i) {
      current = i; render();
      lb.root.classList.add("open");
      lb.root.setAttribute("aria-hidden", "false");
      document.body.style.overflow = "hidden";
      lb.closeBtn.focus();
    }
    function close() {
      stopVideo();
      lb.root.classList.remove("open");
      lb.root.setAttribute("aria-hidden", "true");
      document.body.style.overflow = "";
      if (items[current]) items[current].focus();
    }
    function next() { current = (current + 1) % items.length; render(); }
    function prev() { current = (current - 1 + items.length) % items.length; render(); }
    function stopVideo() {
      try { lb.video.pause(); lb.video.removeAttribute("src"); lb.video.load(); } catch (e) {}
    }

    function render() {
      stopVideo();
      var it = items[current];
      var kind = it.getAttribute("data-kind");
      var dl = it.getAttribute("data-download");
      if (kind === "video") {
        lb.img.style.display = "none";
        lb.video.style.display = "block";
        lb.video.src = it.getAttribute("data-video");
        lb.video.play().catch(function () {});
      } else {
        lb.video.style.display = "none";
        lb.img.style.display = "block";
        var grande = it.getAttribute("data-preview") || "";
        var medio = grande.replace("/preview/", "/thumb2x/");
        lb.img.src = (window.innerWidth <= 900 && window.devicePixelRatio <= 2) ? medio : grande;
        lb.img.alt = it.getAttribute("data-alt") || "";
      }
      lb.conta.textContent = T("di", {a: current + 1, b: items.length});
      if (dl) { lb.dl.href = dl; lb.dl.style.display = "inline-flex"; }
      else { lb.dl.style.display = "none"; }
      precarica(current + 1); precarica(current - 1);
    }

    function precarica(i) {
      if (i < 0 || i >= items.length) return;
      var it = items[i];
      if (it.getAttribute("data-kind") === "video") return;
      var u = it.getAttribute("data-preview");
      if (u) { var im = new Image(); im.src = u; }
    }

    lb.closeBtn.addEventListener("click", close);
    lb.nextBtn.addEventListener("click", next);
    lb.prevBtn.addEventListener("click", prev);
    lb.root.addEventListener("click", function (e) { if (e.target === lb.root) close(); });

    var x0 = null, y0 = null;
    lb.root.addEventListener("touchstart", function (e) {
      if (e.touches.length !== 1) return;
      x0 = e.touches[0].clientX; y0 = e.touches[0].clientY;
    }, { passive: true });
    lb.root.addEventListener("touchend", function (e) {
      if (x0 === null) return;
      var dx = e.changedTouches[0].clientX - x0;
      var dy = e.changedTouches[0].clientY - y0;
      if (Math.abs(dx) > 55 && Math.abs(dx) > Math.abs(dy) * 1.5) {
        if (dx < 0) next(); else prev();
      } else if (dy > 90 && Math.abs(dy) > Math.abs(dx) * 1.5) {
        close();
      }
      x0 = y0 = null;
    }, { passive: true });

    document.addEventListener("keydown", function (e) {
      if (!lb.root.classList.contains("open")) return;
      if (e.key === "Escape") close();
      else if (e.key === "ArrowRight") next();
      else if (e.key === "ArrowLeft") prev();
      else if (e.key === "Home") { current = 0; render(); }
      else if (e.key === "End") { current = items.length - 1; render(); }
    });
  }

  function build() {
    var root = document.createElement("div");
    root.className = "lightbox";
    root.setAttribute("aria-hidden", "true");
    root.setAttribute("role", "dialog");
    root.setAttribute("aria-modal", "true");
    root.setAttribute("aria-label", T("visualizzatore"));
    var img = document.createElement("img");
    var video = document.createElement("video");
    video.setAttribute("controls", "");
    video.setAttribute("playsinline", "");
    video.style.display = "none";
    video.className = "lb-video";
    var closeBtn = mk("button", "lb-close", "&times;", T("chiudi"));
    var prevBtn = mk("button", "lb-nav prev", "&#8249;", T("precedente"));
    var nextBtn = mk("button", "lb-nav next", "&#8250;", T("successiva"));
    var conta = document.createElement("div");
    conta.className = "lb-count";
    var actions = document.createElement("div");
    actions.className = "lb-actions";
    var dl = document.createElement("a");
    dl.className = "btn btn-accent";
    dl.textContent = T("scarica_orig");
    dl.setAttribute("download", "");
    actions.appendChild(dl);
    [img, video, closeBtn, prevBtn, nextBtn, conta, actions].forEach(function (el) {
      root.appendChild(el);
    });
    return { root: root, img: img, video: video, closeBtn: closeBtn,
             prevBtn: prevBtn, nextBtn: nextBtn, dl: dl, conta: conta };
  }

  function mk(t, c, h, l) {
    var e = document.createElement(t);
    e.className = c; e.innerHTML = h; e.type = "button";
    if (l) e.setAttribute("aria-label", l);
    return e;
  }

  document.addEventListener("DOMContentLoaded", function () {
    initLazyLoad();
    initGrid();
  });
})();
