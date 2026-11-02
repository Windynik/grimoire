// Export menu of the editor: copy or download the saved deck as plain text,
// Arena text, or CSV. The export reads the saved deck, so the caller's
// beforeExport hook sends any pending edit first.

import { h } from "../shared/dom.js";
import * as api from "./api.js";

const KINDS = [
  { kind: "text", label: "Plain text", copy: true, file: "deck.txt" },
  { kind: "arena", label: "Arena", copy: true, file: "deck-arena.txt" },
  { kind: "csv", label: "CSV", copy: false, file: "deck.csv" },
];

/**
 * Render the export menu into root.
 *
 * @param {HTMLElement} root
 * @param {string} deckId
 * @param {{beforeExport: function(): Promise<void> (rejects when the deck is not saved), toast: function(string, string)}} [hooks]
 */
export function renderExportMenu(root, deckId, hooks = {}) {
  const before = async () => {
    if (hooks.beforeExport) await hooks.beforeExport();
  };
  const toast = (message, type) => {
    if (hooks.toast) hooks.toast(message, type);
  };
  const details = h("details", { class: "export-menu" });

  async function copy(kind) {
    try {
      await before();
    } catch (error) {
      toast(`Could not save the deck: ${error.message}`, "error");
      return;
    }
    try {
      const text = await api.exportText(deckId, kind);
      await navigator.clipboard.writeText(text);
      toast("Copied", "success");
      details.open = false;
    } catch (error) {
      toast(`Could not copy the deck: ${error.message}`, "error");
    }
  }

  async function download(link) {
    try {
      await before();
    } catch (error) {
      toast(`Could not save the deck: ${error.message}`, "error");
      return;
    }
    // The pending save is now sent, so a plain link click reads the newest deck.
    link.dataset.ready = "true";
    link.click();
    delete link.dataset.ready;
    details.open = false;
  }

  const rows = KINDS.map(({ kind, label, copy: canCopy, file }) => {
    const link = h("a", {
      class: "export-btn", href: api.exportUrl(deckId, kind), download: file,
      "aria-label": `Download ${label}`, text: "Download",
    });
    link.addEventListener("click", (event) => {
      if (link.dataset.ready) return;
      event.preventDefault();
      download(link);
    });
    const actions = h("span", { class: "export-actions" });
    if (canCopy) {
      actions.append(h("button", {
        type: "button", class: "export-btn", "aria-label": `Copy ${label}`, text: "Copy",
        onclick: () => copy(kind),
      }));
    }
    actions.append(link);
    return h("li", { class: "export-row" }, h("span", { class: "export-label", text: label }), actions);
  });

  details.append(
    h("summary", { class: "btn btn-secondary btn-compact", text: "Export" }),
    h("ul", { class: "export-list" }, rows));
  details.addEventListener("focusout", (event) => {
    if (!details.contains(event.relatedTarget)) details.open = false;
  });
  root.replaceChildren(details);
}
