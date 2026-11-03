import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadApp } from "./harness.mjs";

let app;
let document;
let card;
let modal;
let toast;

before(async () => {
  app = await loadApp({
    routes: {
      "GET /api/cache/status": () => ({ json: { cached: false, card_count: 0 } }),
      "GET /api/collections": () => ({ json: { collections: [] } }),
    },
  });
  document = app.document;
  card = await import("../../../frontend/js/shared/card.js");
  modal = await import("../../../frontend/js/shared/modal.js");
  toast = await import("../../../frontend/js/shared/toast.js");
});

const panel = () => document.querySelector("dialog.dialog-panel");
const flipButton = () => panel()?.querySelector(".flip-btn");
const detailImage = () => panel().querySelector(".modal-card-image .card-img-sharp");

test("a double-faced card flips in the detail", async () => {
  card.showCardDetail({ name: "Delver", image_url: "front.jpg", back_image_url: "back.jpg" });
  const button = flipButton();
  assert.ok(button, "Flip button exists");
  assert.equal(button.getAttribute("aria-pressed"), "false");
  assert.ok(detailImage().src.endsWith("front.jpg"));

  button.click();
  assert.equal(button.getAttribute("aria-pressed"), "true");
  await app.until(() => detailImage().src.endsWith("back.jpg"));

  button.click();
  assert.equal(button.getAttribute("aria-pressed"), "false");
  await app.until(() => detailImage().src.endsWith("front.jpg"));
  panel().querySelector(".modal-close").click();
  assert.equal(panel(), null);
});

test("a one-faced card has no Flip button", () => {
  card.showCardDetail({ name: "Island", image_url: "island.jpg", type_line: "Basic Land" });
  assert.ok(panel());
  assert.equal(flipButton(), null);
  panel().querySelector(".modal-close").click();
});

test("the detail puts card text in as text, and keeps mana markup", () => {
  card.showCardDetail({
    name: "<img src=x onerror=boom>", mana_cost: "{1}{U}", oracle_text: "<b>{T}</b>: draw",
  });
  const p = panel();
  assert.equal(p.querySelector(".card-detail-name").textContent, "<img src=x onerror=boom>");
  assert.equal(p.querySelectorAll(".modal-mana .mana").length, 2);
  assert.equal(p.querySelector(".oracle-text b"), null);
  assert.match(p.querySelector(".oracle-text").textContent, /<b>/);
  p.querySelector(".modal-close").click();
});

test("confirmDialog resolves false on Cancel and true on confirm", async () => {
  const no = modal.confirmDialog({ title: "Delete?", message: "Sure?", confirmLabel: "Delete" });
  const dialog = document.querySelector("dialog.dialog");
  assert.match(dialog.textContent, /Sure\?/);
  [...dialog.querySelectorAll("button")].find((b) => b.textContent === "Cancel").click();
  assert.equal(await no, false);
  assert.equal(document.querySelector("dialog.dialog"), null);

  const yes = modal.confirmDialog({ title: "Delete?", message: "Sure?", confirmLabel: "Delete" });
  [...document.querySelectorAll("dialog.dialog button")].find((b) => b.textContent === "Delete").click();
  assert.equal(await yes, true);
});

test("openDialog resolves null on Escape and returns focus", async () => {
  const opener = document.createElement("button");
  document.body.append(opener);
  opener.focus();
  const result = modal.openDialog({ title: "T", content: [], submitLabel: "Go", onSubmit: () => 1 });
  const dialog = document.querySelector("dialog.dialog");
  dialog.dispatchEvent(new app.window.Event("cancel", { cancelable: true }));
  assert.equal(await result, null);
  assert.equal(document.activeElement, opener);
  opener.remove();
});

test("a drag from a field to the backdrop keeps the dialog open", async () => {
  const result = modal.openDialog({
    title: "Paste", content: document.createElement("textarea"), submitLabel: "Go",
  });
  const dialog = document.querySelector("dialog.dialog");
  const field = dialog.querySelector("textarea");
  const fire = (target, type) => target.dispatchEvent(
    new app.window.MouseEvent(type, { bubbles: true, cancelable: true }));

  fire(field, "pointerdown");
  fire(dialog, "click");
  assert.ok(dialog.isConnected, "a press in the field must not close the dialog");

  fire(dialog, "pointerdown");
  fire(dialog, "click");
  assert.equal(await result, null);
  assert.equal(dialog.isConnected, false);
});

test("openDialog keeps the dialog open when onSubmit throws", async () => {
  let calls = 0;
  const result = modal.openDialog({
    title: "T", content: [], submitLabel: "Go",
    onSubmit: async () => {
      calls += 1;
      if (calls === 1) throw new Error("Name is taken");
      return { ok: true };
    },
  });
  const dialog = document.querySelector("dialog.dialog");
  dialog.querySelector("form").dispatchEvent(new app.window.Event("submit", { cancelable: true }));
  await app.until(() => !dialog.querySelector('[role="alert"]').hidden);
  assert.equal(dialog.querySelector('[role="alert"]').textContent, "Name is taken");
  assert.ok(dialog.isConnected);
  await app.until(() => !dialog.querySelector('button[type="submit"]').disabled);

  dialog.querySelector("form").dispatchEvent(new app.window.Event("submit", { cancelable: true }));
  assert.deepEqual(await result, { ok: true });
  assert.equal(dialog.isConnected, false);
});

test("toasts cap at 4", () => {
  for (let i = 0; i < 6; i += 1) toast.showToast(`message ${i}`, "info");
  const items = [...document.querySelectorAll("#toast-container .toast")];
  assert.equal(items.length, 4);
  assert.equal(items[0].textContent, "message 2");
  assert.equal(items[3].textContent, "message 5");
});

test("a toast takes its type as a class", () => {
  toast.showToast("bad", "error");
  assert.ok(document.querySelector("#toast-container .toast.error"));
});
