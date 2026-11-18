// Failure messages give the reason. Audit: toasts such as "Could not load the forge
// setup" and "The request failed." dropped the detail that the server sent.
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { loadApp } from "./harness.mjs";

const AI_UP = { available: true, models: ["qwen3.5:9b"], default_model: "qwen3.5:9b", recommended: "qwen3.5:9b" };
const PRICES = {
  provider: "cardkingdom", active: "cardkingdom", date: "2026-11-13", downloaded: "2026-11-14T08:00:00Z",
  providers: [{ key: "scryfall", label: "TCGplayer", note: "", needs_download: false, cards: 9 },
    { key: "cardkingdom", label: "Card Kingdom", note: "", needs_download: true, cards: 9 }],
};
const entry = (name, id) => ({
  scryfall_id: id, name, count: 1, basic: false, role: "", reason: "",
  image_url: "", mana_cost: "{1}", type_line: "Artifact", cmc: 1, price: 0, set: "tst",
});
const DECK = {
  id: "d1", name: "Deck One", format: "commander", collection_job_id: null, commander: null,
  sections: { main: [entry("Card A", "id-a")], sideboard: [], maybeboard: [] }, analysis: {},
};

let app;
let document;
let window;

before(async () => {
  app = await loadApp({
    hash: "#forge",
    storage: { welcomeSkipped: "1" },
    routes: {
      "GET /api/cache/status": () => ({ json: { status: "ready", card_count: 1 } }),
      "GET /api/collections": () => ({ json: { collections: [] } }),
      "GET /api/decks": () => ({ json: { decks: [] } }),
      "GET /api/ai/status": () => ({ json: AI_UP }),
      "GET /api/forge/formats": () => ({ status: 503, json: { detail: "The card data is loading. Try again in a moment." } }),
    },
  });
  document = app.document;
  window = app.window;
});

// Leave the editor, so its save queue stops.
after(async () => {
  window.location.hash = "#decks";
  await app.settle();
});

const $ = (sel) => document.querySelector(sel);
const toasts = () => [...document.querySelectorAll("#toast-container .toast")].map((el) => el.textContent);
const clearToasts = () => document.getElementById("toast-container").replaceChildren();
const click = (el) => el.dispatchEvent(new window.MouseEvent("click", { bubbles: true, cancelable: true }));
async function go(hash, view) {
  window.location.hash = hash;
  await app.until(() => document.getElementById(`${view}-view`).classList.contains("active"));
}
async function confirm() {
  await app.until(() => document.querySelector("dialog[open]"));
  [...document.querySelectorAll("dialog[open] button")].find((b) => b.type === "submit").click();
}

test("the Forge setup failure gives the server's reason", async () => {
  await app.until(() => toasts().length > 0);
  assert.deepEqual(toasts(), ["Could not load the forge setup: The card data is loading. Try again in a moment."]);
  // An error with no answer from the server adds no raw error text.
  clearToasts();
  app.route("GET /api/forge/formats", () => { throw new TypeError("Failed to fetch"); });
  await go("#decks", "decks");
  await go("#forge", "forge");
  await app.until(() => toasts().length > 0);
  assert.deepEqual(toasts(), ["Could not load the forge setup."]);
});

test("the deck agent failure gives the server's reason", async () => {
  app.route("GET /api/decks/d1", () => ({ json: DECK }));
  app.route("PUT /api/decks/d1", () => ({ json: { analysis: {} } }));
  app.route("GET /api/cards/search", () => ({ json: { cards: [], total: 0 } }));
  app.route("POST /api/decks/d1/agent", () => ({ status: 502, json: { detail: "The model did not give a usable answer. Try again." } }));
  await go("#decks", "decks");
  window.location.hash = "#deck/d1";
  await app.until(() => !document.getElementById("deck-editor").hidden
    && document.querySelector('[data-editor="shell"]:not([hidden])'));
  click(document.querySelector('[data-editor="side-tab"][data-side="agent"]'));
  const input = document.querySelector(".agent-input");
  await app.until(() => !input.disabled);
  input.value = "Cut one card";
  click(document.querySelector(".agent-send"));
  await app.until(() => document.querySelector(".agent-error"));
  assert.equal(document.querySelector(".agent-error").textContent,
    "The agent could not answer: The model did not give a usable answer. Try again.");

  app.route("POST /api/decks/d1/agent", () => { throw new TypeError("Failed to fetch"); });
  await app.until(() => !input.disabled);
  input.value = "Cut another card";
  click(document.querySelector(".agent-send"));
  await app.until(() => document.querySelectorAll(".agent-error").length === 2);
  assert.equal([...document.querySelectorAll(".agent-error")][1].textContent, "The agent could not answer.");
  await go("#decks", "decks");
  await app.until(() => document.getElementById("deck-editor").hidden);
});

test("Settings failures give the server's reason", async () => {
  app.route("GET /api/phone", () => ({ json: { enabled: false, running: false, port: 8135, urls: [], devices: [], pair: null, error: null } }));
  app.route("GET /api/prices", () => ({ json: PRICES }));
  app.route("DELETE /api/prices", () => ({ status: 500, json: { detail: "The price file is locked." } }));
  app.route("DELETE /api/cache", () => ({ status: 500, json: { detail: "Permission denied." } }));
  app.route("DELETE /api/images", () => ({ status: 500, json: { detail: "The images folder is read-only." } }));
  clearToasts();
  await go("#settings", "settings");
  await app.until(() => $("#settings-price-remove") && !$("#settings-price-remove").hidden);
  $("#settings-price-remove").click();
  await confirm();
  await app.until(() => toasts().includes("Could not remove the store prices: The price file is locked."));
  $("#settings-clear-cache").click();
  await confirm();
  await app.until(() => toasts().includes("Could not clear the card data: Permission denied."));
  $("#settings-images-remove").click();
  await confirm();
  await app.until(() => toasts().includes("Could not remove the card images: The images folder is read-only."));

  app.route("GET /api/prices", () => ({ status: 500, json: { detail: "The price file is damaged." } }));
  await go("#decks", "decks");
  await go("#settings", "settings");
  await app.until(() => $("#settings-price-status").textContent
    === "Could not read the price settings: The price file is damaged.");
});

test("the welcome screen gives the reason of a failed card data check", async () => {
  app.route("GET /api/cache/status", () => ({ status: 500, json: { detail: "The card data file is damaged." } }));
  clearToasts();
  await go("#welcome", "welcome");
  await app.until(() => toasts().includes("Could not check the card data: The card data file is damaged."));
  app.route("GET /api/cache/status", () => ({ json: { status: "ready", card_count: 1 } }));
});

test("an import refused without a plain reason gives what the server sent", async () => {
  await go("#import", "import");
  const paste = () => {
    document.querySelector("details.import-paste").open = true;
    document.getElementById("import-paste-text").value = "1 Sol Ring";
    document.getElementById("import-paste-go").click();
  };
  app.route("POST /api/process/text", () => ({ status: 422, json: { detail: [{ msg: "Field required" }, { msg: "Text too short" }] } }));
  clearToasts();
  paste();
  await app.until(() => toasts().length > 0);
  assert.deepEqual(toasts(), ["Field required; Text too short"]);
  app.route("POST /api/process/text", () => ({ status: 500, body: "Internal Server Error" }));
  clearToasts();
  paste();
  await app.until(() => toasts().length > 0);
  assert.deepEqual(toasts(), ["The import stopped. Grimoire answered 500."]);

  app.route("GET /api/collections", () => ({ json: { collections: [] } }));
  app.route("POST /api/process/sample", () => ({ status: 500, body: "Internal Server Error" }));
  window.localStorage.removeItem("welcomeSkipped");
  clearToasts();
  await go("#welcome", "welcome");
  await app.until(() => $("#welcome-sample") && !$("#welcome-sample").disabled && $("#welcome-sample").offsetParent !== undefined);
  await app.until(() => document.getElementById("welcome-view").dataset.step === "2");
  $("#welcome-sample").click();
  await app.until(() => toasts().length > 0);
  assert.deepEqual(toasts(), ["The import stopped. Grimoire answered 500."]);
});
