// Rahmen der Oberfläche: Seitenleiste und Belege-Spalten stufenlos ziehen (ein Griff-Code für beide), „[“ klappt um, Breite im Browser gemerkt;
// das Jahr der Kopfleiste schickt sich bei Wahl selbst ab; Hell/Dunkel über das Sonnen-Symbol, im Browser gemerkt. Ohne Inline-Skript (CSP).
(function () {
  "use strict";
  var WIDE = 208;
  var root = document.documentElement;
  root.classList.add("js");

  // Ein Griff für jede ziehbare Grenze (Seitenleiste, Belege). Der Griff trägt seine Einstellung:
  // data-griff-var (CSS-Variable), -key (Speicherschlüssel), -min/-max (px),
  // -ziel (Selektor des Elements, dessen Breite er setzt; sonst sein Elternelement), -rest (px, die dem Rest bleiben, Rahmen = Elternelement),
  // -schmal (Seitenleiste: unter dieser Breite trägt <html> die Klasse „schmal“).
  var STEP = 16, BIG = 64;
  function config(grip) {
    var d = grip.dataset;
    return {
      name: d.griffVar, key: d.griffKey, min: parseInt(d.griffMin, 10), max: parseInt(d.griffMax, 10),
      rest: parseInt(d.griffRest || "0", 10), narrow: parseInt(d.griffSchmal || "0", 10), target: d.griffZiel
    };
  }
  function apply(cfg, grip, px, remember) {
    var max = cfg.max;
    if (cfg.rest && grip && grip.parentElement) max = Math.min(max, grip.parentElement.getBoundingClientRect().width - cfg.rest);
    px = Math.max(cfg.min, Math.min(Math.max(cfg.min, max), Math.round(px)));
    root.style.setProperty(cfg.name, px + "px");
    if (cfg.narrow) root.classList.toggle("schmal", px < cfg.narrow);
    if (grip) grip.setAttribute("aria-valuenow", String(px));
    if (remember) {
      try { localStorage.setItem(cfg.key, String(px)); } catch (e) { /* ohne Speicher: nur jetzt */ }
    }
    return px;
  }
  function saved(key) {
    try { return parseInt(localStorage.getItem(key) || "", 10) || null; } catch (e) { return null; }
  }
  // Schon im <head>, damit die gemerkte Seitenleiste ohne Springen erscheint (Werte wie am Griff in base.html).
  var early = saved("seitenleiste");
  if (early) apply({ name: "--seitenleiste", key: "seitenleiste", min: 52, max: 380, rest: 0, narrow: 110 }, null, early, false);

  var grips = new WeakMap();
  function initGrip(grip) {
    if (grips.has(grip)) return grips.get(grip);
    var cfg = config(grip);
    var target = cfg.target ? document.querySelector(cfg.target) : grip.parentElement;
    function width() { return target ? target.getBoundingClientRect().width : cfg.min; }
    var api = {
      set: function (px, remember) { return apply(cfg, grip, px, remember); },
      width: width,
      reset: function () {
        root.style.removeProperty(cfg.name);
        if (cfg.narrow) root.classList.remove("schmal");
        try { localStorage.removeItem(cfg.key); } catch (e) { /* ohne Speicher: nur jetzt */ }
        grip.setAttribute("aria-valuenow", String(Math.round(width())));
      }
    };
    grips.set(grip, api);
    grip.setAttribute("aria-valuemin", String(cfg.min));
    grip.setAttribute("aria-valuemax", String(cfg.max));
    var start = saved(cfg.key);
    if (start) api.set(start, false); else grip.setAttribute("aria-valuenow", String(Math.round(width())));
    grip.addEventListener("mousedown", function (down) {
      down.preventDefault();
      var x0 = down.clientX, w0 = width();
      function move(e) { api.set(w0 + e.clientX - x0, true); }
      function up() {
        document.removeEventListener("mousemove", move);
        document.removeEventListener("mouseup", up);
      }
      document.addEventListener("mousemove", move);
      document.addEventListener("mouseup", up);
    });
    grip.addEventListener("dblclick", api.reset);
    grip.addEventListener("keydown", function (e) {
      if (e.altKey || e.ctrlKey || e.metaKey) return;
      var step = e.shiftKey ? BIG : STEP, w = width(), next;
      if (e.key === "ArrowLeft") next = w - step;
      else if (e.key === "ArrowRight") next = w + step;
      else if (e.key === "Home") next = cfg.min;
      else if (e.key === "End") next = cfg.max;
      else if (e.key === "Enter") { e.preventDefault(); api.reset(); return; }
      else return;
      e.preventDefault();
      api.set(next, true);
    });
    return api;
  }
  window.moarcoalGriff = { init: initGrip };

  // Darstellung: leer folgt dem System, sonst "hell" oder "dunkel" (app.css, Farb-Tokens).
  var THEME = "darstellung";
  function setTheme(value) {
    if (value === "hell" || value === "dunkel") root.setAttribute("data-darstellung", value);
    else root.removeAttribute("data-darstellung");
  }
  var theme = "";
  try { theme = localStorage.getItem(THEME) || ""; } catch (e) { theme = ""; }
  setTheme(theme);

  document.addEventListener("DOMContentLoaded", function () {
    Array.prototype.forEach.call(document.querySelectorAll(".griff"), initGrip);
    var side = document.querySelector(".seitenleiste .griff");
    document.addEventListener("keydown", function (e) {
      if (e.key !== "[" || e.ctrlKey || e.altKey || e.metaKey) return;
      var t = e.target;
      if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
      if (!side) return;
      var cfg = config(side);
      initGrip(side).set(root.classList.contains("schmal") ? WIDE : cfg.min, true);
    });
    var year = document.querySelector(".jahrwahl select");
    if (year) year.addEventListener("change", function () { year.form.requestSubmit(); });
    var toggle = document.querySelector("button.darstellung");
    if (toggle) {
      toggle.addEventListener("click", function () {
        // Umschalten gegen das, was gerade zu sehen ist (auch wenn noch das System bestimmt).
        var current = root.getAttribute("data-darstellung") ||
          (matchMedia("(prefers-color-scheme: dark)").matches ? "dunkel" : "hell");
        var next = current === "dunkel" ? "hell" : "dunkel";
        setTheme(next);
        try { localStorage.setItem(THEME, next); } catch (e) { /* ohne Speicher: nur jetzt */ }
      });
    }
  });
})();
