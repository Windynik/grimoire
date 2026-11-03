// Dialogs built on <dialog>. One ".dialog" style serves all of them.

import { h } from "./dom.js";
import { animate } from "./motion.js";

const FIELDS = "input, select, textarea";

function open(dialog) {
  const before = document.activeElement;
  document.body.append(dialog);
  dialog.showModal();
  animate(dialog, [
    { opacity: 0, transform: "translateY(12px)" },
    { opacity: 1, transform: "translateY(0)" },
  ], { duration: "base" });
  return before;
}

// Close the dialog, remove it, and give focus back. Return a function that runs once.
function closer(dialog, before, done) {
  let closed = false;
  return (value) => {
    if (closed) return;
    closed = true;
    if (dialog.open) dialog.close();
    dialog.remove();
    if (before && typeof before.focus === "function" && before.isConnected) before.focus();
    done(value);
  };
}

// Escape and a click on the backdrop close the dialog. The body wraps all content,
// so a click that lands on the dialog itself is a backdrop click. The press must
// start on the backdrop too: a drag that selects text in a field and ends on the
// backdrop must not close the dialog.
function wireDismiss(dialog, close) {
  let pressedOnDialog = false;
  dialog.addEventListener("pointerdown", (event) => {
    pressedOnDialog = event.target === dialog;
  });
  dialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    close(null);
  });
  dialog.addEventListener("click", (event) => {
    const backdropClick = event.target === dialog && pressedOnDialog;
    pressedOnDialog = false;
    if (backdropClick) close(null);
  });
}

/**
 * Open a form dialog.
 *
 * onSubmit(form) may return a value or a promise. The dialog closes and the
 * promise resolves with that value (true when onSubmit returns undefined). A
 * thrown Error shows its message in the alert line and the dialog stays open.
 * Cancel, Escape and a backdrop click resolve null.
 *
 * @param {Object} options
 * @param {string} options.title
 * @param {Node|string|Array} [options.content] Nodes for the form body.
 * @param {string} options.submitLabel
 * @param {string} [options.cancelLabel]
 * @param {boolean} [options.danger] Style the submit button as a danger action.
 * @param {function(HTMLFormElement): any} [options.onSubmit]
 * @returns {Promise<any|null>}
 */
export function openDialog({
  title, content, submitLabel, cancelLabel = "Cancel", danger = false, onSubmit,
}) {
  return new Promise((resolve) => {
    const titleId = `dialog-title-${Math.random().toString(36).slice(2, 8)}`;
    const alert = h("p", { class: "dialog-alert", role: "alert", hidden: true });
    const submit = h("button", { type: "submit", class: `btn ${danger ? "btn-danger" : "btn-primary"}` },
      submitLabel);
    const cancel = h("button", { type: "button", class: "btn btn-secondary" }, cancelLabel);
    const body = h("div", { class: "dialog-content" }, content);
    const form = h("form", { class: "dialog-form", method: "dialog" },
      h("h2", { class: "dialog-title", id: titleId, text: title }),
      body, alert, h("div", { class: "dialog-actions" }, cancel, submit));
    const dialog = h("dialog", { class: "dialog", "aria-labelledby": titleId },
      h("div", { class: "dialog-body" }, form));

    const before = open(dialog);
    const close = closer(dialog, before, resolve);
    wireDismiss(dialog, close);
    cancel.addEventListener("click", () => close(null));
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (submit.disabled) return;
      submit.disabled = true;
      alert.hidden = true;
      try {
        const result = onSubmit ? await onSubmit(form) : undefined;
        close(result === undefined ? true : result);
      } catch (error) {
        alert.textContent = error && error.message ? error.message : String(error);
        alert.hidden = false;
        submit.disabled = false;
      }
    });

    // A destructive dialog starts on Cancel, so Enter does not delete by accident.
    const first = body.querySelector(`[autofocus], ${FIELDS}`);
    (first || (danger ? cancel : submit)).focus();
  });
}

/**
 * Ask the owner to confirm an action.
 *
 * @returns {Promise<boolean>}
 */
export async function confirmDialog({ title, message, confirmLabel, danger = true }) {
  const result = await openDialog({
    title,
    content: h("p", { class: "dialog-message", text: message }),
    submitLabel: confirmLabel,
    danger,
  });
  return result === true;
}

/**
 * Open a dialog with no form, such as the card detail.
 *
 * @param {Object} options
 * @param {string} options.label The accessible name.
 * @param {Node|string|Array} options.content
 * @param {string} [options.className] Extra class for the dialog.
 * @returns {{close: function(): void}}
 */
export function showPanel({ label, content, className }) {
  const closeButton = h("button", {
    type: "button", class: "modal-close", "aria-label": `Close ${label.toLowerCase()}`,
  }, "×");
  const dialog = h("dialog", {
    class: `dialog dialog-panel ${className || ""}`.trim(), "aria-label": label,
  }, h("div", { class: "dialog-body" }, closeButton, content));

  const before = open(dialog);
  const close = closer(dialog, before, () => {});
  wireDismiss(dialog, close);
  closeButton.addEventListener("click", () => close());
  closeButton.focus();
  return { close: () => close() };
}
