// Aussteller-Feld (Vorlage _issuer_field.html): kein Inline-Skript, die CSP erlaubt nur dieses.
// Tippen verwirft die Auswahl; ein Treffer setzt seinen Namen ins Feld.
document.addEventListener("input", (event) => {
  const field = event.target instanceof Element && event.target.closest(".aussteller-feld .suche");
  field?.closest("fieldset")?.querySelector("[name=issuer_choice]")?.remove();
});
// Nach dem Tippen sucht die Anfrage mit `clear`, damit die Vorbelegung nicht zurückkommt.
document.addEventListener("htmx:configRequest", (event) => {
  const { elt, triggeringEvent, parameters } = event.detail;
  if (!elt.matches?.(".aussteller-feld")) return;
  if (triggeringEvent?.type === "input") parameters.clear = "1";
  // Nur die Dokumentart (Auswahlliste) löst beim Ändern eine Suche aus; sonst überholt das
  // „change“ beim Verlassen des Textfelds den Klick auf einen Treffer. Kein Filter im
  // hx-trigger, der bräuchte eval.
  if (triggeringEvent?.type === "change" && triggeringEvent.target?.tagName !== "SELECT") event.preventDefault();
});
document.addEventListener("htmx:afterSwap", (event) => {
  const fieldset = event.target instanceof Element && event.target.closest(".aussteller-feld");
  const chosen = fieldset?.querySelector("[data-name]");
  const input = fieldset?.querySelector(".suche");
  if (chosen instanceof HTMLElement && input instanceof HTMLInputElement) input.value = chosen.dataset.name ?? "";
});
