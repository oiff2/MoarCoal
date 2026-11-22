// Gemeinsames Verhalten (Frage 5), angesteuert nur über data-Attribute, ohne Inline-Skript (CSP):
//   data-darstellung-setzen / -umschalten  Hell/Dunkel/System, im Browser gemerkt (URL ?d= gewinnt)
//   data-merken="schluessel"               <details> merkt offen/zu
//   data-umschalten                        Chip an/aus (aria-pressed)
//   data-pfeile                            Pfeiltasten springen zwischen den Zeilen einer Liste
(function () {
  "use strict";
  var root = document.documentElement;
  function lies(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }
  function schreib(key, value) { try { localStorage.setItem(key, value); } catch (e) { /* ohne Speicher: nur jetzt */ } }

  var aus_url = new URLSearchParams(location.search).get("d");
  var darstellung = aus_url && aus_url !== "system" ? aus_url : (lies("optik-darstellung") || "system");
  function setze(wert) {
    darstellung = wert;
    root.setAttribute("data-darstellung", wert);
    schreib("optik-darstellung", wert);
    document.querySelectorAll("[data-darstellung-setzen]").forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.dataset.darstellungSetzen === wert));
    });
  }
  setze(darstellung);
  document.querySelectorAll("[data-darstellung-setzen]").forEach(function (b) {
    b.addEventListener("click", function () { setze(b.dataset.darstellungSetzen); });
  });
  document.querySelectorAll("[data-darstellung-umschalten]").forEach(function (b) {
    b.addEventListener("click", function () {
      var dunkel = getComputedStyle(root).colorScheme === "dark" || (darstellung === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
      setze(dunkel ? "hell" : "dunkel");
    });
  });

  document.querySelectorAll("details[data-merken]").forEach(function (d) {
    var key = "optik-offen-" + d.dataset.merken;
    var saved = lies(key);
    if (saved !== null) d.open = saved === "1";
    d.addEventListener("toggle", function () { schreib(key, d.open ? "1" : "0"); });
  });

  document.querySelectorAll("[data-umschalten]").forEach(function (b) {
    b.addEventListener("click", function () {
      b.setAttribute("aria-pressed", String(b.getAttribute("aria-pressed") !== "true"));
    });
  });

  document.querySelectorAll("[data-pfeile]").forEach(function (liste) {
    liste.addEventListener("keydown", function (e) {
      if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
      var zeilen = Array.prototype.slice.call(liste.querySelectorAll("tbody tr"));
      var aktuell = zeilen.indexOf(e.target.closest("tr"));
      var ziel = zeilen[aktuell + (e.key === "ArrowDown" ? 1 : -1)];
      var link = ziel && (ziel.querySelector("a, input"));
      if (link) { e.preventDefault(); link.focus(); }
    });
  });
})();
