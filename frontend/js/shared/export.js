// Collection export: fetch the collection CSV and save it. A failed export
// shows the server's reason in a toast. Home and the Vault use it.

import { h } from "./dom.js";
import { showToast } from "./toast.js";

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
