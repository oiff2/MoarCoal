// PROTOTYP #62, Wegwerf
(function () {
  var v = new URLSearchParams(location.search).get("variant") || "A";
  var keys = ["A", "B", "C"];
  function go(d) { var u = new URL(location.href); u.searchParams.set("variant", keys[(keys.indexOf(v) + d + 3) % 3]); location.href = u; }
  document.querySelectorAll(".proto-switch button").forEach(function (b) { b.onclick = function () { go(+b.dataset.dir); }; });
  document.querySelectorAll("a[href^='/']").forEach(function (a) { if (a.pathname.indexOf("/static") !== 0) { a.search = (a.search ? a.search + "&" : "?") + "variant=" + v; } });
  function theme() { var h = document.documentElement; h.dataset.theme = h.dataset.theme === "dark" ? "light" : "dark"; }
  document.querySelectorAll(".theme").forEach(function (b) { b.onclick = theme; });
  document.querySelectorAll(".bpanel-btn").forEach(function (b) { b.onclick = function () { document.body.classList.toggle("nopanel"); }; });
  // aktive Seite markieren
  document.querySelectorAll("[data-key]").forEach(function (a) { if (location.pathname.indexOf(a.pathname) === 0 && a.pathname !== "/") { a.classList.add("on"); } });
  document.addEventListener("keydown", function (e) {
    if (/INPUT|TEXTAREA|SELECT/.test(e.target.tagName)) return;
    if (e.key === "ArrowLeft") go(-1); else if (e.key === "ArrowRight") go(1);
    else if (e.key === "t") theme(); else if (e.key === "b") document.body.classList.toggle("nopanel");
    else { var a = document.querySelector("[data-key='" + e.key + "']"); if (a) a.click(); }
  });
})();
