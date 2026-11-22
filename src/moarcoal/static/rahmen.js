// Gemeinsames Verhalten der Oberfläche, ein Modul, angesteuert nur über data-Attribute der Vorlagen (kein Inline-Skript, CSP):
//   data-griff-*           ziehbare Grenze (Seitenleiste, Belege): -var, -key, -min, -max, -ziel, -rest, -schmal; „[“ klappt die Seitenleiste um
//   data-darstellung-umschalten   Hell/Dunkel (leer folgt dem System), im Browser gemerkt
//   data-absenden          Auswahlliste schickt ihr Formular bei Wahl selbst ab (das Jahr der Kopfleiste)
//   data-merken="schluessel"      <details> merkt offen/zu; der Abschnitt mit der Auswahl (aria-current) bleibt offen
//   data-umschalten="schluessel"  Schalter, im Browser gemerkt; mit data-umschalten-ziel (Selektor) und -klasse schaltet er eine Klasse,
//                          mit data-text-an/-aus wechselt sein Text; ohne Ziel (Chip) schaltet er aria-pressed
//   data-pfeile            Liste: Pfeil hoch/runter wechselt die Datei (a.name), Enter springt zu data-pfeile-enter (Selektor)
// Aller Zugriff auf localStorage läuft über lies/schreib/loesche: nur Bequemlichkeit, ohne Speicher geht jede Seite weiter.
(function () {
  "use strict";
  var WIDE = 208;
  var root = document.documentElement;
  root.classList.add("js");

  function lies(key) {
    try { return localStorage.getItem(key); } catch (e) { return null; }
  }
  function schreib(key, value) {
    try { localStorage.setItem(key, value); } catch (e) { /* ohne Speicher: nur jetzt */ }
  }
  function loesche(key) {
    try { localStorage.removeItem(key); } catch (e) { /* ohne Speicher: nur jetzt */ }
  }

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
    if (remember) schreib(cfg.key, String(px));
    return px;
  }
  function saved(key) {
    return parseInt(lies(key) || "", 10) || null;
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
        loesche(cfg.key);
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

  // Darstellung: leer folgt dem System, sonst "hell" oder "dunkel" (tokens.css, Farb-Tokens).
  var THEME = "darstellung";
  function setTheme(value) {
    if (value === "hell" || value === "dunkel") root.setAttribute("data-darstellung", value);
    else root.removeAttribute("data-darstellung");
  }
  setTheme(lies(THEME) || "");

  function inTextField(t) {
    return t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));
  }

  function initMerken(details) {
    var key = "offen-" + details.dataset.merken;
    // Der Abschnitt mit der Auswahl bleibt offen, damit sie sichtbar ist.
    if (lies(key) === "0" && !details.querySelector("a[aria-current]")) details.open = false;
    details.addEventListener("toggle", function () { schreib(key, details.open ? "1" : "0"); });
  }

  // Schalter mit Zustand: Klasse am Ziel (Detailspalte) oder aria-pressed (Chip); gemerkt unter data-umschalten.
  function initUmschalten(button) {
    var key = button.dataset.umschalten;
    var target = button.dataset.umschaltenZiel ? document.querySelector(button.dataset.umschaltenZiel) : null;
    var cls = button.dataset.umschaltenKlasse;
    function show(on) {
      if (target && cls) {
        target.classList.toggle(cls, on);
        button.setAttribute("aria-expanded", String(!on));
      } else {
        button.setAttribute("aria-pressed", String(on));
      }
      if (button.dataset.textAn && button.dataset.textAus) (button.querySelector(".bt-text") || button).textContent = on ? button.dataset.textAn : button.dataset.textAus;
    }
    var on = key ? lies(key) === "1" : button.getAttribute("aria-pressed") === "true";
    show(on);
    button.addEventListener("click", function () {
      on = !on;
      show(on);
      if (key) schreib(key, on ? "1" : "0");
    });
  }

  // Pfeiltasten wechseln die Datei der Liste, Enter springt ins Formular.
  function initPfeile(list) {
    document.addEventListener("keydown", function (event) {
      if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return;
      var target = event.target;
      if (target instanceof Element && target.closest("input, select, textarea, button, summary")) return;
      if (event.key === "Enter") {
        var field = list.dataset.pfeileEnter ? document.querySelector(list.dataset.pfeileEnter) : null;
        if (field instanceof HTMLElement) {
          event.preventDefault();
          field.focus();
        }
        return;
      }
      var step = { ArrowDown: 1, ArrowUp: -1 }[event.key];
      if (step === undefined) return;
      var links = Array.prototype.filter.call(list.querySelectorAll("a.name"), function (a) { return a.offsetParent !== null; });
      var at = links.findIndex(function (a) { return a.hasAttribute("aria-current"); });
      var next = links[at === -1 ? (step > 0 ? 0 : links.length - 1) : at + step];
      if (next instanceof HTMLAnchorElement) {
        event.preventDefault();
        window.location.href = next.href;
      }
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    Array.prototype.forEach.call(document.querySelectorAll(".griff"), initGrip);
    Array.prototype.forEach.call(document.querySelectorAll("details[data-merken]"), initMerken);
    Array.prototype.forEach.call(document.querySelectorAll("[data-umschalten]"), initUmschalten);
    Array.prototype.forEach.call(document.querySelectorAll("[data-pfeile]"), initPfeile);
    var side = document.querySelector(".seitenleiste .griff");
    document.addEventListener("keydown", function (e) {
      if (e.key !== "[" || e.ctrlKey || e.altKey || e.metaKey) return;
      if (inTextField(e.target) || !side) return;
      var cfg = config(side);
      initGrip(side).set(root.classList.contains("schmal") ? WIDE : cfg.min, true);
    });
    Array.prototype.forEach.call(document.querySelectorAll("select[data-absenden]"), function (select) {
      select.addEventListener("change", function () { select.form.requestSubmit(); });
    });
    Array.prototype.forEach.call(document.querySelectorAll("[data-darstellung-umschalten]"), function (toggle) {
      toggle.addEventListener("click", function () {
        // Umschalten gegen das, was gerade zu sehen ist (auch wenn noch das System bestimmt).
        var current = root.getAttribute("data-darstellung") ||
          (matchMedia("(prefers-color-scheme: dark)").matches ? "dunkel" : "hell");
        var next = current === "dunkel" ? "hell" : "dunkel";
        setTheme(next);
        schreib(THEME, next);
      });
    });
  });
})();
