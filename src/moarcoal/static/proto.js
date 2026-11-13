// PROTOTYP #62 (Runde 3), Wegwerf
(function () {
  var v = new URLSearchParams(location.search).get("variant") || "A";
  var keys = ["A", "B", "C"];
  function go(d) { var u = new URL(location.href); u.searchParams.set("variant", keys[(keys.indexOf(v) + d + 3) % 3]); location.href = u; }
  document.querySelectorAll(".proto-switch button").forEach(function (b) { b.onclick = function () { go(+b.dataset.dir); }; });
  document.querySelectorAll("a[href^='/']").forEach(function (a) { if (a.pathname.indexOf("/static") !== 0) { a.search = (a.search ? a.search + "&" : "?") + "variant=" + v; } });
  function theme() { var h = document.documentElement; h.dataset.theme = h.dataset.theme === "dark" ? "light" : "dark"; }
  document.querySelectorAll(".theme").forEach(function (b) { b.onclick = theme; });
  document.querySelectorAll(".items a").forEach(function (a) { if (location.pathname.indexOf(a.pathname) === 0) a.classList.add("on"); });
  document.querySelectorAll(".grp.foldable").forEach(function (g) { g.onclick = function () { g.classList.toggle("folded"); }; });
  document.querySelectorAll(".rail a[data-path]").forEach(function (a) { if (location.pathname.indexOf(a.pathname) === 0) a.classList.add("on"); });
  var act = document.querySelector(".rail a.on"), ap = act ? act.dataset.path : "/steuerjahr";
  document.querySelectorAll(".subs>div").forEach(function (d) { d.classList.toggle("show", d.dataset.path === ap); });
  var pal = document.querySelector(".palette");
  function palette(open) { if (!pal) return; pal.hidden = !open; if (open) pal.querySelector("input").focus(); }
  var ck = document.querySelector(".cmdk"); if (ck) ck.onclick = function () { palette(true); };
  if (pal) pal.onclick = function (e) { if (e.target === pal) palette(false); };
  document.addEventListener("keydown", function (e) { if (e.ctrlKey && e.key === "k") { e.preventDefault(); palette(pal && pal.hidden); } else if (e.key === "Escape") palette(false); });
  var side = document.querySelector(".side") || document.querySelector(".subpanel");
  var steps = false;
  function width(px) {
    px = Math.max(side.classList.contains("side") ? 52 : 140, Math.min(380, side.classList.contains("side") ? px : px - 74));
    if (steps) px = px < 100 ? 52 : px < 190 ? 160 : 240;
    document.documentElement.style.setProperty("--side", px + "px");
    if (side.classList.contains("side")) side.classList.toggle("compact", px < 110);
  }
  document.querySelector(".grip").onmousedown = function (e) { e.preventDefault(); document.onmousemove = function (m) { width(m.clientX); }; document.onmouseup = function () { document.onmousemove = null; }; };
  document.addEventListener("keydown", function (e) {
    if (/INPUT|TEXTAREA|SELECT/.test(e.target.tagName)) return;
    if (e.key === "ArrowLeft") go(-1); else if (e.key === "ArrowRight") go(1);
    else if (e.key === "t") theme();
    else if (e.key === "[" && side.classList.contains("side")) width(side.classList.contains("compact") ? 208 : 52);
    else { var a = document.querySelector("[data-key='" + e.key + "']"); if (a) a.click(); }
  });
})();
