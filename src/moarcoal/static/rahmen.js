// Gemeinsames Verhalten der Oberfläche, ein Modul, angesteuert nur über data-Attribute der Vorlagen (kein Inline-Skript, CSP):
//   data-griff-*           ziehbare Grenze (Seitenleiste, Belege): -var, -key, -min, -max, -ziel, -rest, -andere, -richtung, -schmal; „[“ klappt die Seitenleiste um
//   data-darstellung-umschalten   Hell/Dunkel (leer folgt dem System), im Browser gemerkt
//   data-absenden          Auswahlliste schickt ihr Formular bei Wahl selbst ab (das Jahr der Kopfleiste)
//   data-merken="schluessel"      <details> merkt offen/zu; der Abschnitt mit der Auswahl (aria-current) bleibt offen
//   data-umschalten="schluessel"  Schalter, im Browser gemerkt; mit data-umschalten-ziel (Selektor) und -klasse schaltet er eine Klasse,
//                          mit data-text-an/-aus wechselt sein Text; ohne Ziel (Chip) schaltet er aria-pressed
//   data-pfeile            Liste: Pfeil hoch/runter wechselt die Datei (a.name), Enter springt zu data-pfeile-enter (Selektor)
//   data-karte             Karte der Orte (Arbeit): Mausrad/Pinch zoomt zum Zeiger, Ziehen schwenkt, Knöpfe mit data-karte-zoom (Faktor oder „alles“);
//                          nur die viewBox ändert sich, die Orte (g.pt) behalten per Gegenskalierung ihre Bildschirmgröße
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
  // -andere (Selektor der Griffe der übrigen festen Spalten: ihre Breite, ohne Wert ihr Minimum, zählt zum Rest),
  // -richtung („zurueck“: Spalte rechts vom Griff, Ziehen nach rechts macht sie schmaler),
  // -schmal (Seitenleiste: unter dieser Breite trägt <html> die Klasse „schmal“).
  var STEP = 16, BIG = 64;
  function config(grip) {
    var d = grip.dataset;
    return {
      name: d.griffVar, key: d.griffKey, min: parseInt(d.griffMin, 10), max: parseInt(d.griffMax, 10),
      rest: parseInt(d.griffRest || "0", 10), others: d.griffAndere, back: d.griffRichtung === "zurueck", narrow: parseInt(d.griffSchmal || "0", 10), target: d.griffZiel
    };
  }
  function apply(cfg, grip, px, remember) {
    var max = cfg.max;
    if (cfg.rest && grip && grip.parentElement) {
      var taken = cfg.rest;
      if (cfg.others) {
        Array.prototype.forEach.call(document.querySelectorAll(cfg.others), function (other) {
          var o = config(other);
          taken += parseFloat(root.style.getPropertyValue(o.name)) || o.min;
        });
      }
      max = Math.min(max, grip.parentElement.getBoundingClientRect().width - taken);
    }
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
      function move(e) { api.set(w0 + (cfg.back ? x0 - e.clientX : e.clientX - x0), true); }
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
      var grow = cfg.back ? "ArrowLeft" : "ArrowRight", shrink = cfg.back ? "ArrowRight" : "ArrowLeft";
      if (e.key === shrink) next = w - step;
      else if (e.key === grow) next = w + step;
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

  // Karte: Ausschnitt = viewBox (gleiches Seitenverhältnis wie das ganze Land, daher keine Neuberechnung beim Ändern der Spaltenbreite;
  // Zeigerpositionen werden bei jedem Ereignis aus dem aktuellen Rechteck der Karte umgerechnet).
  var MAX_ZOOM = 40;
  function initKarte(box) {
    var svg = box.querySelector("svg.deutschlandkarte");
    if (!svg || !svg.viewBox || !svg.viewBox.baseVal) return;
    var full = { x: 0, y: 0, w: svg.viewBox.baseVal.width, h: svg.viewBox.baseVal.height };
    if (!(full.w > 0 && full.h > 0)) return;
    var view = { x: full.x, y: full.y, w: full.w, h: full.h };
    var points = Array.prototype.map.call(svg.querySelectorAll("g.pt"), function (g) {
      var m = /translate\(\s*(-?[\d.]+)[ ,]+(-?[\d.]+)\s*\)/.exec(g.getAttribute("transform") || "");
      return m ? { g: g, x: m[1], y: m[2] } : null;
    }).filter(Boolean);
    function show() {
      svg.setAttribute("viewBox", [view.x, view.y, view.w, view.h].join(" "));
      var k = full.w / view.w;
      svg.style.setProperty("--karte-zoom", String(k));
      points.forEach(function (p) { p.g.setAttribute("transform", "translate(" + p.x + " " + p.y + ") scale(" + 1 / k + ")"); });
    }
    function clamp() {
      view.w = Math.max(full.w / MAX_ZOOM, Math.min(full.w, view.w));
      view.h = view.w * full.h / full.w;
      view.x = Math.max(full.x, Math.min(full.x + full.w - view.w, view.x));
      view.y = Math.max(full.y, Math.min(full.y + full.h - view.h, view.y));
    }
    // Zoomt um den Bildschirmpunkt (cx, cy) so, dass der Kartenpunkt darunter liegen bleibt.
    function zoom(factor, cx, cy) {
      var r = svg.getBoundingClientRect();
      var fx = r.width ? (cx - r.left) / r.width : 0.5, fy = r.height ? (cy - r.top) / r.height : 0.5;
      var px = view.x + fx * view.w, py = view.y + fy * view.h;
      view.w /= factor;
      clamp();
      view.x = px - fx * view.w;
      view.y = py - fy * view.h;
      clamp();
      show();
    }
    function pan(dx, dy) {
      var r = svg.getBoundingClientRect();
      if (!r.width) return;
      view.x -= dx * view.w / r.width;
      view.y -= dy * view.h / r.height;
      clamp();
      show();
    }
    svg.addEventListener("wheel", function (e) {
      e.preventDefault();
      // Pinch auf dem Trackpad kommt als Rad mit ctrlKey und feinen Schritten.
      zoom(Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0015)), e.clientX, e.clientY);
    }, { passive: false });
    var pointers = new Map(), last = null;
    function spread() {
      var a = Array.from(pointers.values());
      return { d: Math.hypot(a[0].x - a[1].x, a[0].y - a[1].y), x: (a[0].x + a[1].x) / 2, y: (a[0].y + a[1].y) / 2 };
    }
    svg.addEventListener("pointerdown", function (e) {
      if (e.pointerType === "mouse" && e.button !== 0) return;
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      try { svg.setPointerCapture(e.pointerId); } catch (err) { /* ohne Capture: Ziehen endet am Rand */ }
      svg.classList.add("zieht");
      last = pointers.size === 2 ? spread() : null;
    });
    svg.addEventListener("pointermove", function (e) {
      var p = pointers.get(e.pointerId);
      if (!p) return;
      var dx = e.clientX - p.x, dy = e.clientY - p.y;
      p.x = e.clientX;
      p.y = e.clientY;
      if (pointers.size === 1) pan(dx, dy);
      else if (pointers.size === 2) {
        var now = spread();
        if (last && last.d > 0) zoom(now.d / last.d, now.x, now.y);
        if (last) pan(now.x - last.x, now.y - last.y);
        last = now;
      }
    });
    function release(e) {
      pointers.delete(e.pointerId);
      last = pointers.size === 2 ? spread() : null;
      if (!pointers.size) svg.classList.remove("zieht");
    }
    svg.addEventListener("pointerup", release);
    svg.addEventListener("pointercancel", release);
    Array.prototype.forEach.call(box.querySelectorAll("[data-karte-zoom]"), function (button) {
      button.addEventListener("click", function () {
        var value = button.dataset.karteZoom;
        if (value === "alles") {
          view.x = full.x; view.y = full.y; view.w = full.w; view.h = full.h;
          show();
        } else {
          var r = svg.getBoundingClientRect();
          zoom(parseFloat(value), r.left + r.width / 2, r.top + r.height / 2);
        }
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    Array.prototype.forEach.call(document.querySelectorAll("[data-karte]"), initKarte);
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
