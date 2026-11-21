// Belege und Arbeit: Pfeiltasten wechseln die Datei der Liste, Enter springt ins Formular.
document.addEventListener("keydown", (event) => {
  if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return;
  const target = event.target;
  if (target instanceof Element && target.closest("input, select, textarea, button, summary")) return;
  if (event.key === "Enter") {
    const field = document.querySelector(".formular input:not([type=hidden])");
    if (field instanceof HTMLElement) {
      event.preventDefault();
      field.focus();
    }
    return;
  }
  const step = { ArrowDown: 1, ArrowUp: -1 }[event.key];
  if (step === undefined) return;
  // Auf einer Seite zum Scrollen (Arbeit) wechseln die Pfeiltasten nur, wenn die Liste den Fokus hat.
  if (!document.querySelector(".baum") && !(target instanceof Element && target.closest(".liste"))) return;
  const links = [...document.querySelectorAll(".baum a.name, .liste a.name")].filter((a) => a.offsetParent !== null);
  const at = links.findIndex((a) => a.hasAttribute("aria-current"));
  const next = links[at === -1 ? (step > 0 ? 0 : links.length - 1) : at + step];
  if (next instanceof HTMLAnchorElement) {
    event.preventDefault();
    window.location.href = next.href;
  }
});
document.querySelector(".baum a[aria-current]")?.scrollIntoView({ block: "nearest" });
// „aus Name“ verschwindet, sobald der Nutzer das Feld ändert.
for (const mark of document.querySelectorAll("[data-aus-name]")) {
  const owner = mark.closest("label, fieldset");
  const clear = () => mark.remove();
  owner?.addEventListener("input", clear, { once: true });
  owner?.addEventListener("change", clear, { once: true });
  owner?.addEventListener("click", (e) => e.target instanceof Element && e.target.closest("button") && clear());
}
// Ein Klick auf eine Zeile der Liste wählt sie (wie ihr Name); Links, Knöpfe und Formulare behalten ihre Aufgabe.
document.querySelector(".baum")?.addEventListener("click", (event) => {
  const target = event.target;
  if (event.defaultPrevented || !(target instanceof Element) || target.closest("a, button, form, input, select, summary")) return;
  const link = target.closest(".datei")?.querySelector("a.name");
  if (link instanceof HTMLAnchorElement) window.location.href = link.href;
});
// Detailspalte ein- und ausblenden; der Browser merkt es sich (nur Bequemlichkeit, ohne Speicher geht die Seite weiter).
(() => {
  const toggle = document.querySelector("[data-detailspalte-schalter]");
  const page = document.querySelector(".arbeit");
  if (!(toggle instanceof HTMLElement) || !page) return;
  const KEY = "detailspalte-aus";
  const apply = (off) => {
    page.classList.toggle("ohne-detail", off);
    toggle.textContent = off ? "Detailspalte einblenden" : "Detailspalte ausblenden";
    toggle.setAttribute("aria-expanded", String(!off));
  };
  let off = false;
  try { off = localStorage.getItem(KEY) === "1"; } catch (e) { off = false; }
  apply(off);
  toggle.addEventListener("click", () => {
    off = !off;
    apply(off);
    try { localStorage.setItem(KEY, off ? "1" : "0"); } catch (e) { /* ohne Speicher: nur jetzt */ }
  });
})();
// Eingeklappte Abschnitte der Liste bleiben es über Seitenwechsel; ohne Speicher oder ohne Skript sind alle offen.
// Das Skript läuft ohne defer hinter den Abschnitten, also vor der ersten Darstellung (kein Flackern).
(() => {
  const KEY = "belege-abschnitte-zu";
  const sections = [...document.querySelectorAll("details.abschnitt[id]")];
  let closed = [];
  try { closed = JSON.parse(localStorage.getItem(KEY) || "[]"); } catch (e) { closed = []; }
  if (!Array.isArray(closed)) closed = [];
  for (const section of sections) {
    // Der Abschnitt mit der Auswahl bleibt offen, damit sie sichtbar ist.
    if (closed.includes(section.id) && !section.querySelector("a[aria-current]")) section.open = false;
  }
  for (const section of sections) {
    section.addEventListener("toggle", () => {
      const now = sections.filter((s) => !s.open).map((s) => s.id);
      try { localStorage.setItem(KEY, JSON.stringify(now)); } catch (e) { /* ohne Speicher: nur jetzt */ }
    });
  }
})();
// Spaltengriff: Breite der Liste ziehen (Logik und Speicher wie bei der Seitenleiste, rahmen.js); sofort, damit die gemerkte Breite nicht springt.
for (const grip of document.querySelectorAll(".arbeit > .griff")) window.moarcoalGriff?.init(grip);
