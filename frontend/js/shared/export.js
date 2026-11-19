// Collection export: the Export menu, and the download of one format. A failed
// export shows the server's reason in a toast. Home and the Collection screen
// use the same menu.

import { h } from "./dom.js";
import { showToast } from "./toast.js";

/** The formats of the Export menu, in menu order: [kind, label]. */
export const EXPORT_KINDS = [
  ["enhanced", "CSV with card data"],
  ["manabox", "ManaBox CSV"],
  ["moxfield", "Moxfield CSV"],
  ["archidekt", "Archidekt CSV"],
  ["deckbox", "Deckbox CSV"],
  ["list", "Card list (text)"],
];

// The file name ending of each export kind. "enhanced" is the imported CSV
// with the card data added; the others are the formats of other apps.
const SUFFIX = {
  enhanced: ".csv", manabox: " (ManaBox).csv", moxfield: " (Moxfield).csv",
  archidekt: " (Archidekt).csv", deckbox: " (Deckbox).csv", list: ".txt",
};

/**
 * Download one collection as a file.
 *
 * @param {{job_id: string, name: string}} collection
 * @param {string} [kind] "enhanced" (default), "manabox", "moxfield", "archidekt", "deckbox" or "list".
 */
export async function exportCollection(collection, kind = "enhanced") {
  const suffix = SUFFIX[kind] || ".csv";
  const query = kind === "enhanced" ? "" : `?kind=${encodeURIComponent(kind)}`;
  try {
    const res = await fetch(`/api/collection/${encodeURIComponent(collection.job_id)}/export${query}`);
    if (!res.ok) {
      let detail = `Export failed (HTTP ${res.status})`;
      try {
        const body = await res.json();
        if (body && typeof body.detail === "string") detail = body.detail;
      } catch (e) {
        // The body is not JSON: keep the status text.
      }
      showToast(detail, "error");
      return;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const link = h("a", { href: url, download: `${collection.name || "collection"}${suffix}` });
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) {
    showToast("Error exporting collection", "error");
  }
}

// One listener serves every menu: a click outside an open menu closes it, and
// Escape closes the menu that has the focus.
let listening = false;

function listen() {
  if (listening) return;
  listening = true;
  document.addEventListener("click", (event) => {
    document.querySelectorAll("details.collection-export-menu[open]").forEach((menu) => {
      if (!menu.contains(event.target)) menu.open = false;
    });
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    const menu = event.target && event.target.closest && event.target.closest("details.collection-export-menu[open]");
    if (!menu) return;
    menu.open = false;
    menu.querySelector("summary").focus();
  });
}

/**
 * The Export menu of one collection: a summary that opens the list of formats.
 * Each choice closes the menu and downloads the collection in that format.
 *
 * @param {function(): ({job_id: string, name: string}|null)} collectionOf The
 *   collection to export. The menu reads it at each choice.
 * @param {Object} [options]
 * @param {string} [options.id] The id of the menu (one menu per page only).
 * @param {string} [options.summaryClass] The classes of the summary, so it looks like its neighbors.
 * @param {string} [options.label] The accessible name of the summary, such as "Export Binder".
 * @param {string} [options.title] The tooltip of the summary.
 * @returns {HTMLDetailsElement}
 */
export function exportMenu(collectionOf, options = {}) {
  listen();
  const summary = h("summary", {
    class: options.summaryClass || "", "aria-label": options.label, title: options.title, text: "Export",
  });
  const list = h("div", { class: "collection-export-list", role: "menu", "aria-label": "Export formats" },
    ...EXPORT_KINDS.map(([kind, label]) => h("button", {
      type: "button", role: "menuitem", "data-kind": kind, text: label,
    })));
  const menu = h("details", { class: "collection-export-menu", id: options.id }, summary, list);
  list.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-kind]");
    if (!button) return;
    menu.open = false;
    const collection = collectionOf();
    if (collection) exportCollection(collection, button.dataset.kind);
  });
  return menu;
}
