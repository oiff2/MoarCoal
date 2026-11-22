// Belege-Seite: nur, was nur sie braucht. Pfeiltasten, Detailspalte, gemerkte Abschnitte und Spaltenbreite stehen in rahmen.js (data-Attribute).
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
