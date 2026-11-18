import { esc } from "./catalog.js";

export function createColumnFilters({ list, choice, add, groups, placeholder, fields, onChange }) {
  const columns = new Map([...groups.values()].flat().map((column) => [column.key, column]));
  const active = new Map();

  function updateChoices() {
    const options = [...groups].map(([group, columns]) => {
      const available = columns.filter(({ key }) => !active.has(key));
      return available.length ? `<optgroup label="${esc(group)}">${available.map(({ key, label }) =>
        `<option value="${esc(key)}">${esc(label)}</option>`).join("")}</optgroup>` : "";
    });
    choice.innerHTML = `<option value="">${esc(placeholder)}</option>` + options.join("");
    choice.disabled = active.size === columns.size;
    add.disabled = true;
  }

  function notify(addedKey) {
    onChange([...active].map(([key, values]) => ({ key, ...values })), addedKey);
  }

  choice.addEventListener("change", () => { add.disabled = !choice.value; });
  add.addEventListener("click", () => {
    const column = columns.get(choice.value);
    if (!column || active.has(column.key)) return;
    const { key, label } = column;
    const bounds = fields(column);
    const row = document.createElement("fieldset");
    row.className = "column-filter";
    row.dataset.attribute = key;
    row.innerHTML = `<legend>${esc(label)}</legend>
      <div class="pair">${Object.entries(bounds).map(([bound, field]) => {
        const name = { min: "Min", max: "Max", top: "Top %" }[bound];
        const fullName = { min: "minimum", max: "maximum", top: "top percent" }[bound];
        return `<label>${name}<input type="${field.type}" inputmode="${field.inputMode ?? "decimal"}" autocomplete="off"
          data-bound="${bound}" aria-label="${esc(label)} ${fullName}" ${field.attributes}></label>`;
      }).join("")}</div>
      <p id="${list.id}-${key}-error" class="filter-error" role="status" hidden></p>
      <button class="link column-filter-remove" type="button" aria-label="Remove ${esc(label)} filter">Remove</button>`;
    list.append(row);
    const inputs = [...row.querySelectorAll("input")];
    const error = row.querySelector(".filter-error");
    const values = {};
    for (const input of inputs) {
      const bound = input.dataset.bound;
      values[bound] = null;
      input.setAttribute("aria-describedby", error.id);
      input.addEventListener("input", () => {
        const field = bounds[bound];
        const value = input.value.trim() === "" ? null : field.parse(input);
        const invalid = input.validity.badInput || (value !== null && !Number.isFinite(value));
        if (invalid) input.setAttribute("aria-invalid", "true");
        else input.removeAttribute("aria-invalid");
        values[bound] = invalid ? null : value;
        const firstInvalid = inputs.find((item) => item.hasAttribute("aria-invalid"));
        error.textContent = firstInvalid ? bounds[firstInvalid.dataset.bound].error : "";
        error.hidden = !firstInvalid;
        notify();
      });
    }
    row.querySelector("button").addEventListener("click", () => {
      row.remove();
      active.delete(key);
      updateChoices();
      choice.focus();
      notify();
    });
    active.set(key, values);
    updateChoices();
    inputs[0].focus();
    notify(key);
  });

  updateChoices();
  return {
    clear() {
      active.clear();
      list.replaceChildren();
      updateChoices();
    },
  };
}
