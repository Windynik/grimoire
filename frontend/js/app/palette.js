// Command palette: Cmd-K (Ctrl-K) opens a box that jumps to a screen, runs an
// action, opens a saved deck, or searches the Vault for the typed text.
//
// The palette is a modal dialog with a combobox and a listbox: the arrow keys
// move the active option, Enter runs it, Escape closes the palette, and the
// focus goes back to where it was. Deck names go in with textContent only.

import { h } from "../shared/dom.js";
import { getJSON } from "../shared/http.js";
import { navigate } from "./router.js";

const MAX_SHOWN = 12;

// The fixed commands: [label, group, words to match, run].
const COMMANDS = [
  ["Home", "Go to", "home start", () => navigate("#home")],
  ["Collection (the Vault)", "Go to", "collection vault cards binder", () => navigate("#collection")],
  ["Deck Forge", "Go to", "forge build ai", () => navigate("#forge")],
  ["Decks", "Go to", "decks list", () => navigate("#decks")],
  ["Settings", "Go to", "settings prices images phone model", () => navigate("#settings")],
  ["Import cards", "Action", "import csv upload add cards collection", () => navigate("#import")],
  ["New deck", "Action", "new create deck", () => navigate("#decks", { newDeck: true })],
  ["Import a decklist", "Action", "import paste decklist deck", () => navigate("#decks", { importDeck: true })],
  ["Forgotten gems", "Action", "gems forgotten unused popular", () => navigate("#collection", { q: "is:gem" })],
  ["Cards for trade", "Action", "trade flag binder", () => navigate("#collection", { q: "flag:trade" })],
];

let ui = null;
let decks = [];
let items = [];
let active = 0;
let opener = null;

/** Rank the commands for a query: every word must appear; a label that starts with the query comes first. */
export function rank(query, entries) {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return entries.slice();
  const scored = [];
  entries.forEach((entry, order) => {
    const hay = `${entry.label} ${entry.group} ${entry.words || ""}`.toLowerCase();
    if (!words.every((w) => hay.includes(w))) return;
    const label = entry.label.toLowerCase();
    const score = label.startsWith(words.join(" ")) ? 0 : label.includes(words[0]) ? 1 : 2;
    scored.push([score, order, entry]);
  });
  return scored.sort((a, b) => a[0] - b[0] || a[1] - b[1]).map((s) => s[2]);
}

function entries() {
  const fixed = COMMANDS.map(([label, group, words, run]) => ({ label, group, words, run }));
  const saved = decks.map((d) => ({
    label: String(d.name || "Untitled deck"), group: "Deck", words: `deck ${d.format || ""} ${d.commander || ""}`,
    run: () => navigate(`#deck/${encodeURIComponent(d.id)}`),
  }));
  return [...fixed, ...saved];
}

function build() {
  const input = h("input", {
    id: "palette-input", class: "palette-input", type: "text", role: "combobox", autocomplete: "off",
    spellcheck: "false", "aria-expanded": "true", "aria-controls": "palette-list", "aria-autocomplete": "list",
    placeholder: "Go to a screen, open a deck, or search your cards…", "aria-label": "Command",
  });
  const list = h("ul", { id: "palette-list", class: "palette-list", role: "listbox", "aria-label": "Commands" });
  const hint = h("p", { class: "palette-hint", text: "↑ ↓ to move · Enter to open · Esc to close" });
  const box = h("div", { class: "palette-box", role: "dialog", "aria-modal": "true", "aria-label": "Command palette" },
    input, list, hint);
  const root = h("div", { class: "palette", id: "palette", hidden: true }, box);
  root.addEventListener("mousedown", (event) => { if (event.target === root) close(); });
  input.addEventListener("input", () => { active = 0; render(); });
  input.addEventListener("keydown", onKey);
  document.body.append(root);
  return { root, input, list };
}

function render() {
  const query = ui.input.value.trim();
  items = rank(query, entries()).slice(0, MAX_SHOWN);
  if (query) {
    items.unshift({ label: `Search the Vault for “${query}”`, group: "Search",
      run: () => navigate("#collection", { q: query }) });
  }
  active = Math.max(0, Math.min(active, items.length - 1));
  ui.list.replaceChildren(...items.map((item, i) => {
    const option = h("li", { id: `palette-option-${i}`, class: "palette-option", role: "option",
      "aria-selected": String(i === active) },
    h("span", { class: "palette-label", text: item.label }),
    h("span", { class: "palette-group", text: item.group }));
    option.addEventListener("mousemove", () => { if (active !== i) { active = i; paint(); } });
    option.addEventListener("click", () => runAt(i));
    return option;
  }));
  if (!items.length) {
    ui.list.append(h("li", { class: "palette-empty", role: "presentation", text: "Nothing matches." }));
  }
  paint();
}

function paint() {
  ui.list.querySelectorAll(".palette-option").forEach((el, i) => el.setAttribute("aria-selected", String(i === active)));
  const current = ui.list.querySelector(`#palette-option-${active}`);
  if (current) {
    ui.input.setAttribute("aria-activedescendant", current.id);
    if (current.scrollIntoView) current.scrollIntoView({ block: "nearest" });
  } else {
    ui.input.removeAttribute("aria-activedescendant");
  }
}

function runAt(index) {
  const item = items[index];
  if (!item) return;
  close(false);
  item.run();
}

function onKey(event) {
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    if (!items.length) return;
    active = (active + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
    paint();
  } else if (event.key === "Enter") {
    event.preventDefault();
    runAt(active);
  } else if (event.key === "Escape") {
    event.preventDefault();
    close();
  } else if (event.key === "Tab") {
    // The input is the only control: the focus stays in the dialog.
    event.preventDefault();
  }
}

export function isOpen() {
  return Boolean(ui && !ui.root.hidden);
}

/** Open the palette. The saved decks load in the background. */
export async function openPalette() {
  if (!ui) ui = build();
  if (isOpen()) return;
  opener = document.activeElement;
  ui.input.value = "";
  active = 0;
  ui.root.hidden = false;
  document.body.classList.add("palette-open");
  render();
  ui.input.focus();
  try {
    const data = await getJSON("/decks");
    decks = (data && data.decks) || [];
    if (isOpen()) render();
  } catch (error) {
    // Without the decks, the palette still has the screens and the actions.
  }
}

/** Close the palette. The focus goes back to the control that had it. */
export function close(restore = true) {
  if (!isOpen()) return;
  ui.root.hidden = true;
  document.body.classList.remove("palette-open");
  if (restore && opener && opener.focus && opener.isConnected) opener.focus();
  opener = null;
}

/** Listen for Cmd-K and Ctrl-K, and for the top bar's search button. */
export function startPalette() {
  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && !event.altKey && event.key.toLowerCase() === "k") {
      event.preventDefault();
      if (isOpen()) close();
      else openPalette();
    }
  });
  const button = document.getElementById("palette-button");
  if (button) button.addEventListener("click", () => openPalette());
}
