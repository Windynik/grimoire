// A Forge run that fails. Audit bug 3: after the failure the cards kept orbiting
// and the ring still showed the progress of the stage that failed ("20%").
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { loadApp } from "./harness.mjs";

const FAILURE = "No deck plan fits the cards you own in Commander.";
const sources = [];

// jsdom has no EventSource. This one records each stream, and the test sends the events.
class FakeEventSource {
  static CLOSED = 2;

  constructor(url) {
    this.url = url;
    this.readyState = 1;
    this.listeners = {};
    sources.push(this);
  }

  addEventListener(type, fn) {
    (this.listeners[type] ||= []).push(fn);
  }

  close() {
    this.readyState = FakeEventSource.CLOSED;
  }

  emit(type, data, id) {
    (this.listeners[type] || []).forEach((fn) => fn({ data: JSON.stringify(data), lastEventId: String(id) }));
  }
}

let app;
let document;

before(async () => {
  globalThis.EventSource = FakeEventSource;
  globalThis.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  app = await loadApp({
    hash: "#decks",
    storage: { welcomeSkipped: "1" },
    routes: {
      "GET /api/cache/status": () => ({ json: { status: "ready", card_count: 10 } }),
      "GET /api/collections": () => ({ json: { collections: [] } }),
      "GET /api/decks": () => ({ json: { decks: [] } }),
      "GET /api/forge/formats": () => ({ json: { formats: [] } }),
      "GET /api/ai/status": () => ({ json: { available: false, models: [] } }),
    },
  });
  document = app.document;
  // A saved forge id (in sessionStorage) makes the Forge screen attach to that run.
  app.window.sessionStorage.setItem("forgeId", "f1");
  app.window.location.hash = "#forge";
});

// Stop the stage loop and the timers, so the test process can exit.
after(() => {
  app.window.location.hash = "#decks";
  app.window.close();
});

const transforms = () => [...document.querySelectorAll(".forge-card")].map((card) => card.style.transform);
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

test("a failed run stops the cards and the progress", async () => {
  const source = await app.until(() => sources.find((s) => s.url.endsWith("/forge/f1/events")));
  const cards = ["A", "B", "C"].map((name) => ({ id: `id-${name}`, name, image_url: "" }));
  source.emit("stage", { index: 0, progress: 1 }, 1);
  source.emit("cards", { cards }, 2);
  source.emit("stage", { index: 1, progress: 0 }, 3);
  source.emit("error", { message: FAILURE }, 4);
  await app.until(() => document.getElementById("forge-status").textContent === FAILURE, 8000);

  assert.equal(document.querySelector(".forge-pct").textContent, "Failed");
  assert.ok(document.getElementById("forge-run").classList.contains("is-halted"));
  const first = transforms();
  assert.equal(first.length, 3);
  await pause(150);
  assert.deepEqual(transforms(), first, "the cards stay still after the failure");
  assert.equal(document.getElementById("forge-new").hidden, false);
});
