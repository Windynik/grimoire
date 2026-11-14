// The command palette: Cmd-K / Ctrl-K, the button, the ranking, the keys.
import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadApp } from "./harness.mjs";

let app;
let document;
let window;

before(async () => {
  app = await loadApp({
    reducedMotion: true,
    storage: { welcomeSkipped: "1" },
    routes: {
      "GET /api/cache/status": () => ({ json: { status: "missing" } }),
      "GET /api/collections": () => ({ json: { collections: [] } }),
      "GET /api/decks": () => ({ json: { decks: [
        { id: "d1", name: "Goblin Tribal", format: "commander", commander: "Krenko, Mob Boss" },
        { id: "d2", name: "Mono Blue Tempo", format: "modern", commander: null }] } }),
    },
  });
  document = app.document;
  window = app.window;
});

const $ = (sel) => document.querySelector(sel);
const labels = () => [...document.querySelectorAll(".palette-option .palette-label")].map((n) => n.textContent);
const press = (key, init = {}, target = document.activeElement || document.body) =>
  target.dispatchEvent(new window.KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...init }));
const type = async (text) => {
  const input = $("#palette-input");
  input.value = text;
  input.dispatchEvent(new window.Event("input", { bubbles: true }));
  await app.settle();
};

test("Ctrl-K opens the palette with the focus in it, and Escape gives the focus back", async () => {
  const button = $("#palette-button");
  button.focus();
  press("k", { ctrlKey: true });
  await app.until(() => $("#palette") && !$("#palette").hidden);
  assert.equal(document.activeElement, $("#palette-input"));
  assert.equal($(".palette-box").getAttribute("role"), "dialog");
  assert.equal($("#palette-input").getAttribute("aria-controls"), "palette-list");
  await app.until(() => labels().includes("Goblin Tribal"));
  press("Escape");
  assert.equal($("#palette").hidden, true);
  assert.equal(document.activeElement, button);
});

test("typing ranks the commands, the arrows move, and Enter goes there", async () => {
  $("#palette-button").click();
  await app.until(() => !$("#palette").hidden);
  await type("sett");
  assert.equal(labels()[0], "Search the Vault for “sett”");
  assert.equal(labels()[1], "Settings");
  press("ArrowDown");
  const input = $("#palette-input");
  assert.equal(input.getAttribute("aria-activedescendant"), "palette-option-1");
  assert.equal($("#palette-option-1").getAttribute("aria-selected"), "true");
  press("Enter");
  await app.until(() => window.location.hash === "#settings");
  assert.equal($("#palette").hidden, true);
});

test("a deck opens by its name or its commander", async () => {
  press("k", { metaKey: true });
  await app.until(() => !$("#palette").hidden && labels().includes("Goblin Tribal"));
  await type("krenko");
  assert.deepEqual(labels(), ["Search the Vault for “krenko”", "Goblin Tribal"]);
  [...document.querySelectorAll(".palette-option")][1].click();
  await app.until(() => window.location.hash === "#deck/d1");
});

test("nothing that matches says so, and the search line stays", async () => {
  press("k", { ctrlKey: true });
  await app.until(() => !$("#palette").hidden);
  await type("zzqx");
  assert.deepEqual(labels(), ["Search the Vault for “zzqx”"]);
  await type("");
  assert.ok(labels().length > 5);
  press("Escape");
});

test("the ranking needs every word and puts a label that starts with the query first", async () => {
  const { rank } = await import("../../../frontend/js/app/palette.js");
  const entries = [
    { label: "Import cards", group: "Action", words: "csv" },
    { label: "Decks", group: "Go to", words: "" },
    { label: "Import a decklist", group: "Action", words: "deck paste" },
  ];
  assert.deepEqual(rank("deck", entries).map((e) => e.label), ["Decks", "Import a decklist"]);
  assert.deepEqual(rank("import deck", entries).map((e) => e.label), ["Import a decklist"]);
  assert.deepEqual(rank("", entries).map((e) => e.label), ["Import cards", "Decks", "Import a decklist"]);
});
