// Settings screen: the About text and "Clear All Data".

import { confirmDialog } from "../shared/modal.js";
import { setActiveCollection } from "../shared/session.js";
import { showToast } from "../shared/toast.js";

const API_BASE = "/api";

async function clearAllData() {
  const ok = await confirmDialog({
    title: "Clear all data",
    message: "Clear the bulk data cache and forget your last collection?",
    confirmLabel: "Clear all data",
  });
  if (!ok) return;

  try {
    await fetch(`${API_BASE}/cache`, { method: "DELETE" });
    setActiveCollection(null);
    // Home reads the archive status again when it opens.
    showToast("All data cleared", "success");
  } catch (error) {
    showToast("Error clearing data", "error");
  }
}

function init() {
  document.getElementById("clear-all-data").addEventListener("click", clearAllData);
}

/** Show the screen. */
export function open() {}

init();
