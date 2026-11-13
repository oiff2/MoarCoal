// Belege: Pfeiltasten wechseln die Datei der Liste, Enter springt ins Formular.
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
  const links = [...document.querySelectorAll(".baum a.name")].filter((a) => a.offsetParent !== null);
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
}
