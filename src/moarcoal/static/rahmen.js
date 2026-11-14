// Rahmen der Oberfläche: Seitenleiste stufenlos ziehen, „[“ klappt um, Breite im Browser gemerkt;
// das Jahr der Kopfleiste schickt sich bei Wahl selbst ab; Hell/Dunkel über das Sonnen-Symbol, im Browser gemerkt. Ohne Inline-Skript (CSP).
(function () {
  "use strict";
  var KEY = "seitenleiste", MIN = 52, MAX = 380, WIDE = 208, NARROW_BELOW = 110;
  var root = document.documentElement;
  root.classList.add("js");

  function setWidth(px, remember) {
    px = Math.max(MIN, Math.min(MAX, Math.round(px)));
    root.style.setProperty("--seitenleiste", px + "px");
    root.classList.toggle("schmal", px < NARROW_BELOW);
    if (remember) {
      try { localStorage.setItem(KEY, String(px)); } catch (e) { /* ohne Speicher: nur jetzt */ }
    }
  }

  // Schon im <head>, damit die gemerkte Breite ohne Springen erscheint.
  var saved = null;
  try { saved = parseInt(localStorage.getItem(KEY) || "", 10); } catch (e) { saved = null; }
  if (saved) setWidth(saved, false);

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
    var grip = document.querySelector(".griff");
    if (grip) {
      grip.addEventListener("mousedown", function (down) {
        down.preventDefault();
        function move(e) { setWidth(e.clientX, true); }
        function up() {
          document.removeEventListener("mousemove", move);
          document.removeEventListener("mouseup", up);
        }
        document.addEventListener("mousemove", move);
        document.addEventListener("mouseup", up);
      });
    }
    document.addEventListener("keydown", function (e) {
      if (e.key !== "[" || e.ctrlKey || e.altKey || e.metaKey) return;
      var t = e.target;
      if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
      setWidth(root.classList.contains("schmal") ? WIDE : MIN, true);
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
