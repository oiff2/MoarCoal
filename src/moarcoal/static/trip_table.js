// Dienstreisen-Tabelle: Pfeiltasten wechseln die Reise, „+ Reise“, „kopieren“ und „Abbrechen“.
// Ohne Skript bleibt die Tabelle benutzbar: eine leere Reise je Speichern, Enter speichert.
const form = document.getElementById("dienstreisen");
if (form instanceof HTMLFormElement) {
  const body = form.querySelector("tbody");
  const count = form.elements.namedItem("zeilen");
  const addButton = document.getElementById("reise-dazu");
  const cancelButton = document.getElementById("abbrechen");
  const savedCount = count.value;
  const PLACE_SPLIT = /\s*(?:→|->|;|\s-\s)\s*/;

  const dataRows = () => [...body.rows].filter((row) => row.querySelector("[data-col]"));
  const cellIn = (row, col) => row?.querySelector(`[data-col="${col}"]`);
  const places = (row) => cellIn(row, 2).value.split(PLACE_SPLIT).filter(Boolean);
  // Wie TripRow.is_blank: keine Daten, km, Notiz und höchstens der vorbelegte Startort.
  const isBlank = (row) =>
    [0, 1, 3, 4].every((col) => !cellIn(row, col).value.trim()) && places(row).length <= 1;

  // Pfeil hoch/runter wechselt in dieselbe Spalte der Reise davor oder danach; im Datumsfeld ändert er nie den Tag.
  form.addEventListener("keydown", (event) => {
    const input = event.target;
    if (!(input instanceof HTMLInputElement) || input.dataset.col === undefined) return;
    if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    if (input.type === "date") event.preventDefault();
    const rows = dataRows();
    const at = rows.indexOf(input.closest("tr"));
    const target = cellIn(rows[at + (event.key === "ArrowUp" ? -1 : 1)], input.dataset.col);
    if (!(target instanceof HTMLInputElement)) return;
    event.preventDefault();
    target.focus();
    if (target.type !== "date" && target.type !== "checkbox") target.select();
  });

  // Das Ende wählt man ab dem Start.
  form.addEventListener("change", (event) => {
    const input = event.target;
    if (input instanceof HTMLInputElement && input.dataset.col === "0") {
      cellIn(input.closest("tr"), 1).min = input.value || input.min;
    }
  });

  // Die letzte, leere Reise kopieren, durchnummerieren und mit dem Startort der Reise davor füllen.
  const addRow = () => {
    const rows = dataRows();
    const last = rows[rows.length - 1];
    const n = parseInt(count.value, 10);
    const copy = last.cloneNode(true);
    copy.removeAttribute("id");
    for (const input of copy.querySelectorAll("input")) {
      input.name = input.name.replace(/-\d+$/, `-${n}`);
      input.removeAttribute("autofocus");
      input.classList.remove("ungueltig");
      input.removeAttribute("title");
      if (input.type === "checkbox") input.checked = false;
      else input.value = "";
    }
    cellIn(copy, 1).min = cellIn(copy, 0).min;
    const start = places(last);
    if (start.length) cellIn(copy, 2).value = `${start[0]} → `;
    copy.dataset.added = "";
    body.appendChild(copy);
    count.value = n + 1;
    cancelButton.hidden = false;
    return copy;
  };

  form.addEventListener("input", () => {
    cancelButton.hidden = false;
  });

  // „Abbrechen“: neue Reisen verwerfen, jedes Feld zurück auf den gespeicherten Stand.
  cancelButton.addEventListener("click", () => {
    for (const row of body.querySelectorAll("tr[data-added]")) row.remove();
    form.reset();
    count.value = savedCount;
    for (const row of dataRows()) cellIn(row, 1).min = cellIn(row, 0).value || cellIn(row, 0).min;
    cancelButton.hidden = true;
  });

  addButton.hidden = false;
  addButton.addEventListener("click", () => cellIn(addRow(), 0).focus());

  // „kopieren“: Orte, km und Notiz in die leere letzte Reise (sonst in eine neue); Daten bleiben leer.
  for (const button of form.querySelectorAll(".reise-kopieren")) {
    button.hidden = false;
    button.addEventListener("click", () => {
      const source = button.closest("tr");
      const rows = dataRows();
      let target = rows[rows.length - 1];
      if (target === source || !isBlank(target)) target = addRow();
      for (const col of [2, 3, 4]) cellIn(target, col).value = cellIn(source, col).value;
      for (const col of [0, 1]) cellIn(target, col).value = "";
      cellIn(target, 1).min = cellIn(target, 0).min;
      cellIn(target, 0).focus();
    });
  }
}
