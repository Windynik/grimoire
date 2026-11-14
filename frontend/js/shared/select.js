// Styled dropdowns. A native <select> opens the operating system's own menu,
// which CSS cannot style. On a computer (a fine pointer) each select gets a
// button and a list in the app's style; on a touch screen the native picker
// stays, because it suits a phone better (base.css styles its closed field).
//
// The native select stays in the page and keeps the value: the button sets
// select.value and fires the same "input" and "change" events, so the screens
// need no change. A change of the options, or of select.value from code,
// shows on the button at once.
//
// The button is a select-only combobox (WAI-ARIA): Enter, Space or the arrows
// open the list; the arrows, Home, End and Page keys move; Enter or Space
// chooses; Escape closes; typing a letter jumps to the next option with it.

import { h } from "./dom.js";

const ENHANCED = new WeakMap();
const PROTO = typeof HTMLSelectElement === "undefined" ? null : HTMLSelectElement.prototype;
const VALUE = PROTO && Object.getOwnPropertyDescriptor(PROTO, "value");
const INDEX = PROTO && Object.getOwnPropertyDescriptor(PROTO, "selectedIndex");
const TYPE_RESET_MS = 600;
const PAGE = 8;
let uid = 0;
let open = null; // the open dropdown: {select, trigger, menu, active}

function labelText(select) {
  const own = (select.getAttribute("aria-label") || "").trim();
  if (own) return own;
  const labels = select.labels && select.labels.length ? [...select.labels]
    : [select.closest("label")].filter(Boolean);
  for (const label of labels) {
    const span = label.querySelector(":scope > span");
    const text = ((span && span.textContent) || label.textContent || "").trim();
    if (text) return text.replace(/\s+/g, " ");
  }
  return "";
}

function optionLabel(option) {
  return (option.label || option.textContent || "").trim();
}

function selectedOption(select) {
  return select.options[INDEX ? INDEX.get.call(select) : select.selectedIndex] || null;
}

function sync(select) {
  const state = ENHANCED.get(select);
  if (!state) return;
  const current = selectedOption(select);
  state.value.textContent = current ? optionLabel(current) : "";
  state.trigger.disabled = select.disabled;
  state.trigger.hidden = select.hidden;
  const name = (select.getAttribute("aria-label") || "").trim() || state.name;
  if (name) state.trigger.setAttribute("aria-label", name);
  if (open && open.select === select) renderMenu();
}

function usable(index) {
  const option = open.select.options[index];
  return Boolean(option) && !option.disabled && !option.hidden;
}

function step(from, delta) {
  const count = open.select.options.length;
  let index = from;
  for (let tries = 0; tries < count; tries += 1) {
    index = Math.max(0, Math.min(count - 1, index + delta));
    if (usable(index)) return index;
    if (index === 0 || index === count - 1) break;
  }
  return usable(from) ? from : index;
}

function renderMenu() {
  const { select, menu, trigger } = open;
  menu.replaceChildren(...[...select.options].map((option, index) => {
    if (option.hidden) return null;
    const item = h("li", {
      id: `${menu.id}-${index}`, class: "gselect-option", role: "option",
      "aria-selected": String(option.selected), "data-index": String(index),
      text: optionLabel(option),
    });
    if (option.disabled) item.setAttribute("aria-disabled", "true");
    return item;
  }).filter(Boolean));
  paint();
  trigger.setAttribute("aria-controls", menu.id);
}

function paint() {
  const { menu, trigger, active } = open;
  menu.querySelectorAll(".gselect-option").forEach((item) => {
    item.classList.toggle("is-active", Number(item.dataset.index) === active);
  });
  const item = menu.querySelector(`[data-index="${active}"]`);
  if (item) {
    trigger.setAttribute("aria-activedescendant", item.id);
    if (typeof item.scrollIntoView === "function") item.scrollIntoView({ block: "nearest" });
  } else {
    trigger.removeAttribute("aria-activedescendant");
  }
}

function place() {
  const { trigger, menu } = open;
  const box = trigger.getBoundingClientRect();
  menu.style.minWidth = `${Math.round(box.width)}px`;
  menu.style.left = `${Math.round(Math.max(8, Math.min(box.left, window.innerWidth - menu.offsetWidth - 8)))}px`;
  const below = window.innerHeight - box.bottom;
  const height = menu.offsetHeight;
  const up = height > below - 12 && box.top > below;
  menu.style.top = `${Math.round(up ? Math.max(8, box.top - height - 6) : box.bottom + 6)}px`;
  menu.classList.toggle("is-up", up);
}

function openMenu(select, start) {
  const state = ENHANCED.get(select);
  if (!state || select.disabled) return;
  if (open) closeMenu(false);
  const menu = h("ul", { id: `gselect-menu-${++uid}`, class: "gselect-menu", role: "listbox", tabindex: "-1" });
  const name = state.trigger.getAttribute("aria-label");
  if (name) menu.setAttribute("aria-label", name);
  const current = INDEX ? INDEX.get.call(select) : select.selectedIndex;
  open = { select, trigger: state.trigger, menu, active: current >= 0 ? current : 0, typed: "", typedAt: 0 };
  if (typeof start === "number") open.active = start;
  if (!usable(open.active)) open.active = step(open.active, 1);
  renderMenu();
  menu.addEventListener("mousedown", (event) => event.preventDefault());
  menu.addEventListener("click", (event) => {
    const item = event.target.closest(".gselect-option");
    if (item && item.getAttribute("aria-disabled") !== "true") choose(Number(item.dataset.index));
  });
  menu.addEventListener("mousemove", (event) => {
    const item = event.target.closest(".gselect-option");
    if (item && Number(item.dataset.index) !== open.active && item.getAttribute("aria-disabled") !== "true") {
      open.active = Number(item.dataset.index);
      paint();
    }
  });
  // Inside an open dialog the list must be in the dialog: a modal dialog makes
  // the rest of the page inert. A popover sits in the top layer, so no
  // dialog, panel or overflow hides it.
  (state.trigger.closest("dialog[open]") || document.body).append(menu);
  if (typeof menu.showPopover === "function") {
    menu.setAttribute("popover", "manual");
    menu.showPopover();
  }
  state.trigger.setAttribute("aria-expanded", "true");
  place();
  paint();
}

function closeMenu(focus = true) {
  if (!open) return;
  const { trigger, menu } = open;
  open = null;
  menu.remove();
  trigger.setAttribute("aria-expanded", "false");
  trigger.removeAttribute("aria-activedescendant");
  if (focus && trigger.isConnected) trigger.focus();
}

function choose(index) {
  const { select } = open;
  closeMenu();
  const before = INDEX ? INDEX.get.call(select) : select.selectedIndex;
  if (index === before || !select.options[index]) return;
  if (INDEX) INDEX.set.call(select, index);
  else select.selectedIndex = index;
  sync(select);
  select.dispatchEvent(new Event("input", { bubbles: true }));
  select.dispatchEvent(new Event("change", { bubbles: true }));
}

// Typing jumps to the next option that starts with the typed letters.
function typeAhead(key) {
  const now = Date.now();
  open.typed = now - open.typedAt > TYPE_RESET_MS ? key : open.typed + key;
  open.typedAt = now;
  const options = [...open.select.options];
  const wanted = open.typed.toLowerCase();
  const startAt = open.typed.length === 1 ? open.active + 1 : open.active;
  for (let i = 0; i < options.length; i += 1) {
    const index = (startAt + i) % options.length;
    if (usable(index) && optionLabel(options[index]).toLowerCase().startsWith(wanted)) {
      open.active = index;
      paint();
      return;
    }
  }
}

function onKey(select, event) {
  const key = event.key;
  const printable = key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey;
  if (!open || open.select !== select) {
    if (["ArrowDown", "ArrowUp", "Enter", " "].includes(key)) {
      event.preventDefault();
      event.stopPropagation();
      openMenu(select);
    } else if (printable) {
      event.preventDefault();
      openMenu(select);
      typeAhead(key);
    }
    return;
  }
  const last = select.options.length - 1;
  const moves = {
    ArrowDown: () => step(open.active, 1), ArrowUp: () => step(open.active, -1),
    Home: () => step(-1, 1), End: () => step(last + 1, -1),
    PageDown: () => step(Math.min(last, open.active + PAGE - 1), 1),
    PageUp: () => step(Math.max(0, open.active - PAGE + 1), -1),
  };
  if (moves[key]) {
    event.preventDefault();
    event.stopPropagation();
    open.active = moves[key]();
    paint();
  } else if (key === "Enter" || key === " ") {
    event.preventDefault();
    event.stopPropagation();
    choose(open.active);
  } else if (key === "Escape") {
    event.preventDefault();
    event.stopPropagation();
    closeMenu();
  } else if (key === "Tab") {
    closeMenu(false);
  } else if (printable) {
    event.preventDefault();
    typeAhead(key);
  }
}

// Code that sets select.value or select.selectedIndex must show on the button.
// The setters of HTMLSelectElement are wrapped once: the wrapper runs the
// original setter, then refreshes the button of an enhanced select. (A
// per-element property does not work everywhere: some DOMs make a select a
// proxy object.)
let patched = false;
function patchSetters() {
  if (patched || !PROTO || !VALUE || !INDEX) return;
  patched = true;
  [["value", VALUE], ["selectedIndex", INDEX]].forEach(([prop, original]) => {
    Object.defineProperty(PROTO, prop, {
      configurable: true,
      enumerable: original.enumerable,
      get: original.get,
      set(v) {
        original.set.call(this, v);
        if (ENHANCED.has(this)) sync(this);
      },
    });
  });
}

/** Give one select the styled button and list. A select with data-native, or a multiple select, stays native. */
export function enhanceSelect(select) {
  if (!select || ENHANCED.has(select) || select.multiple || select.hasAttribute("data-native")) return;
  const value = h("span", { class: "gselect-value" });
  const trigger = h("button", {
    type: "button", class: `gselect ${select.className || ""}`.trim(), role: "combobox",
    "aria-haspopup": "listbox", "aria-expanded": "false",
  }, value, h("span", { class: "gselect-arrow", "aria-hidden": "true" }));
  trigger.id = `${select.id || "gselect"}-button-${++uid}`;
  // Read the label now: once the button is in, a label around both labels the button.
  const name = labelText(select);
  select.before(trigger);
  [...(select.labels || [])].forEach((label) => {
    if (label.htmlFor === select.id && select.id) label.htmlFor = trigger.id;
  });
  select.setAttribute("data-gselect", "");
  select.setAttribute("aria-hidden", "true");
  select.tabIndex = -1;
  ENHANCED.set(select, { trigger, value, name });
  patchSetters();

  trigger.addEventListener("click", () => {
    if (open && open.select === select) closeMenu();
    else openMenu(select);
  });
  trigger.addEventListener("keydown", (event) => onKey(select, event));
  trigger.addEventListener("blur", () => {
    // A click in the list keeps the focus (mousedown is stopped there).
    if (open && open.select === select) closeMenu(false);
  });

  new MutationObserver(() => sync(select)).observe(select, {
    childList: true, subtree: true, characterData: true, attributes: true,
    attributeFilter: ["disabled", "hidden", "aria-label", "selected", "label"],
  });
  sync(select);
}

/** Enhance every select in root, now and as the screens add more. Computers only. */
export function startSelects(root = document.body) {
  const fine = typeof window.matchMedia === "function" && window.matchMedia("(pointer: fine)").matches;
  if (!fine || !root) return false;
  root.querySelectorAll("select").forEach(enhanceSelect);
  new MutationObserver((records) => {
    records.forEach((record) => record.addedNodes.forEach((node) => {
      if (node.nodeType !== 1) return;
      if (node.tagName === "SELECT") enhanceSelect(node);
      else node.querySelectorAll?.("select").forEach(enhanceSelect);
    }));
  }).observe(root, { childList: true, subtree: true });
  // Close the list on a press outside it, and when the page scrolls or resizes.
  document.addEventListener("pointerdown", (event) => {
    if (open && !open.menu.contains(event.target) && !open.trigger.contains(event.target)) closeMenu(false);
  }, true);
  window.addEventListener("scroll", (event) => {
    if (open && !open.menu.contains(event.target)) closeMenu(false);
  }, true);
  window.addEventListener("resize", () => closeMenu(false));
  return true;
}

/** For tests: whether a dropdown list is open. */
export function isOpen() {
  return Boolean(open);
}
