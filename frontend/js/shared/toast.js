// Toasts: short messages in #toast-container.

import { animate } from "./motion.js";

const LIFETIME_MS = 4000;
const MAX_TOASTS = 4;

async function dismiss(toast) {
  if (!toast.isConnected) return;
  toast.dataset.leaving = "true";
  await animate(toast, [{ opacity: 1 }, { opacity: 0 }], { duration: "fast", fill: "forwards" });
  toast.remove();
}

/**
 * Show a toast.
 *
 * @param {string} message
 * @param {"info"|"success"|"error"} [type]
 */
export function showToast(message, type = "info") {
  const container = document.getElementById("toast-container");
  if (!container) return;
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);

  const live = [...container.children];
  live.slice(0, Math.max(0, live.length - MAX_TOASTS)).forEach((old) => old.remove());

  animate(toast, [
    { opacity: 0, transform: "translateX(24px)" },
    { opacity: 1, transform: "translateX(0)" },
  ], { duration: "base" });
  setTimeout(() => dismiss(toast), LIFETIME_MS);
}
