// Custom dropdowns: progressive enhancement over native selects.
// The native select stays in the DOM (hidden) as the source of truth, so
// change handlers on it keep working.

// Each enhanced select maps to the function that redraws its dropdown.
const syncs = new WeakMap();

/** Redraw the dropdown of a select after code changes its value or options. */
export function syncSelect(select) {
  const sync = syncs.get(select);
  if (sync) sync();
}

/** Enhance every filter and sort select under root. */
export function enhanceSelects(root = document) {
  root.querySelectorAll("select.filter-select, select.sort-select").forEach(enhanceSelect);
}

export function enhanceSelect(select) {
  if (syncs.has(select)) return;
  const wrap = document.createElement("div");
  wrap.className = "dropdown";
  select.parentNode.insertBefore(wrap, select);
  wrap.appendChild(select);

  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "dropdown-toggle";
  toggle.setAttribute("aria-haspopup", "listbox");
  toggle.setAttribute("aria-expanded", "false");
  wrap.appendChild(toggle);

  const menu = document.createElement("ul");
  menu.className = "dropdown-menu";
  menu.setAttribute("role", "listbox");
  menu.hidden = true;
  wrap.appendChild(menu);

  let focusedIndex = -1;

  function options() {
    return [...menu.querySelectorAll(".dropdown-option")];
  }

  function sync() {
    const opt = select.options[select.selectedIndex];
    toggle.textContent = opt ? opt.textContent : "—";
    toggle.classList.toggle("active", Boolean(select.value));
    wrap.hidden = select.hidden;
    options().forEach((li) => {
      li.classList.toggle("selected", li.dataset.value === select.value);
      li.setAttribute("aria-selected", String(li.dataset.value === select.value));
    });
  }

  function rebuild() {
    menu.replaceChildren();
    [...select.options].forEach((opt) => {
      const li = document.createElement("li");
      li.className = "dropdown-option";
      li.dataset.value = opt.value;
      li.textContent = opt.textContent;
      li.setAttribute("role", "option");
      li.addEventListener("click", () => {
        select.value = opt.value;
        select.dispatchEvent(new Event("change"));
        close();
        toggle.focus();
      });
      menu.appendChild(li);
    });
    sync();
  }

  function open() {
    menu.hidden = false;
    wrap.classList.add("open");
    toggle.setAttribute("aria-expanded", "true");
    focusedIndex = options().findIndex((li) => li.classList.contains("selected"));
    highlight(focusedIndex);
  }

  function close() {
    menu.hidden = true;
    wrap.classList.remove("open");
    toggle.setAttribute("aria-expanded", "false");
  }

  function highlight(index) {
    options().forEach((li, i) => li.classList.toggle("focused", i === index));
    if (index >= 0) options()[index]?.scrollIntoView({ block: "nearest" });
  }

  toggle.addEventListener("click", () => (menu.hidden ? open() : close()));

  toggle.addEventListener("keydown", (e) => {
    const opts = options();
    if (e.key === "Escape") {
      close();
    } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (menu.hidden) open();
      const delta = e.key === "ArrowDown" ? 1 : -1;
      focusedIndex = Math.max(0, Math.min(opts.length - 1, focusedIndex + delta));
      highlight(focusedIndex);
    } else if ((e.key === "Enter" || e.key === " ") && !menu.hidden && focusedIndex >= 0) {
      e.preventDefault();
      opts[focusedIndex].click();
    }
  });

  document.addEventListener("click", (e) => {
    if (!wrap.contains(e.target)) close();
  });

  select.addEventListener("change", sync);

  // Mirror dynamic option lists (commander picker) and hidden toggling (foil)
  new MutationObserver((mutations) => {
    for (const m of mutations) {
      if (m.type === "childList") rebuild();
      else sync();
    }
  }).observe(select, { childList: true, attributes: true, attributeFilter: ["hidden"] });

  syncs.set(select, sync);
  rebuild();
}
