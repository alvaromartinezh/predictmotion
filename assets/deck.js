/* ===== deck.js · navegación de la presentación =============================
   Sin dependencias. Controla el paso de diapositivas, deep-linking por hash,
   teclado, swipe táctil, barra de progreso y modo índice (overview).
   -------------------------------------------------------------------------- */
(function () {
  "use strict";

  var deck = document.getElementById("deck");
  if (!deck) return;
  var slides = Array.prototype.slice.call(deck.querySelectorAll(".slide"));
  var fill = document.getElementById("deck-progress-fill");
  var counter = document.getElementById("deck-counter");
  var n = slides.length;
  var cur = 0;
  var overview = false;

  function clamp(i) { return Math.max(0, Math.min(n - 1, i)); }

  function render() {
    slides.forEach(function (s, i) { s.classList.toggle("is-active", i === cur); });
    if (fill) fill.style.width = ((cur + 1) / n * 100) + "%";
    if (counter) counter.textContent = (cur + 1) + " / " + n;
    // Notifica a piezas interesadas (p. ej. la demo Monte Carlo).
    document.dispatchEvent(new CustomEvent("deck:slide", { detail: { index: cur, slide: slides[cur] } }));
  }

  function go(i, push) {
    cur = clamp(i);
    if (push !== false) {
      var h = "#" + (cur + 1);
      if (location.hash !== h) history.replaceState(null, "", h);
    }
    render();
    if (!overview) slides[cur].scrollTop = 0;
  }

  function next() { if (cur < n - 1) go(cur + 1); }
  function prev() { if (cur > 0) go(cur - 1); }

  function setOverview(on) {
    overview = on;
    deck.classList.toggle("is-overview", on);
    if (!on) go(cur);
  }
  function toggleOverview() { setOverview(!overview); }

  // ── Teclado ────────────────────────────────────────────────────────────
  document.addEventListener("keydown", function (e) {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    switch (e.key) {
      case "ArrowRight": case "PageDown": case " ": e.preventDefault(); overview ? setOverview(false) : next(); break;
      case "ArrowLeft": case "PageUp": e.preventDefault(); prev(); break;
      case "Home": e.preventDefault(); go(0); break;
      case "End": e.preventDefault(); go(n - 1); break;
      case "o": case "O": e.preventDefault(); toggleOverview(); break;
      case "Escape": if (overview) setOverview(false); break;
      case "f": case "F":
        if (!document.fullscreenElement) { (document.documentElement.requestFullscreen || function () {}).call(document.documentElement); }
        else { document.exitFullscreen(); }
        break;
    }
  });

  // ── Botones ──────────────────────────────────────────────────────────────
  var bPrev = document.getElementById("deck-prev");
  var bNext = document.getElementById("deck-next");
  var bOver = document.getElementById("deck-overview");
  if (bPrev) bPrev.addEventListener("click", prev);
  if (bNext) bNext.addEventListener("click", next);
  if (bOver) bOver.addEventListener("click", toggleOverview);

  // Click en una tarjeta del índice → ir a esa slide.
  slides.forEach(function (s, i) {
    s.addEventListener("click", function () { if (overview) { setOverview(false); go(i); } });
  });

  // ── Swipe táctil ─────────────────────────────────────────────────────────
  var x0 = null;
  deck.addEventListener("touchstart", function (e) { x0 = e.touches[0].clientX; }, { passive: true });
  deck.addEventListener("touchend", function (e) {
    if (x0 === null || overview) { x0 = null; return; }
    var dx = e.changedTouches[0].clientX - x0;
    if (Math.abs(dx) > 50) { dx < 0 ? next() : prev(); }
    x0 = null;
  }, { passive: true });

  // ── Hash inicial + navegación por historial ───────────────────────────────
  function fromHash() {
    var m = /^#(\d+)$/.exec(location.hash);
    return m ? clamp(parseInt(m[1], 10) - 1) : 0;
  }
  window.addEventListener("hashchange", function () { go(fromHash(), false); });

  cur = fromHash();
  render();
})();
