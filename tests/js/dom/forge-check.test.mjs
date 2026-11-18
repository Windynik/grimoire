// The Forge check before a run. Audit: the Forge said "No deck plan fits the cards
// you own in Commander." after the run, and the setup gave no warning before it.
import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadApp } from "./harness.mjs";

const OK = {
  cards: 49, legal: 17, room: 12, need: 10, commanders: 1, deck_size: 100,
  summary: "17 of your 49 cards are legal in Commander. A Commander deck has 100 cards.",
  problem: null, commander_lifts: false,
};
const TOO_FEW = {
  ...OK, legal: 16, room: 6,
  summary: "16 of your 49 cards are legal in Commander. A Commander deck has 100 cards.",
  problem: "A Commander deck needs a commander and at least 10 more different cards in its colors "
    + "that are not lands. The best commander you own has 6. Choose a commander, and the forge "
    + "builds around it with the cards you have.",
  commander_lifts: true,
};
const NO_COMMANDER = {
  ...OK, legal: 15, commanders: 0, room: 0,
  summary: "15 of your 49 cards are legal in Commander. A Commander deck has 100 cards.",
  problem: "A Commander deck needs a commander, and none of your legal cards can be one.",
};

let app;
let document;
let window;
let reply = () => ({ json: OK });
const posts = [];

before(async () => {
  app = await loadApp({
    hash: "#forge",
    routes: {
      "GET /api/cache/status": () => ({ json: { status: "ready", card_count: 1 } }),
      "GET /api/collections": () => ({ json: { collections: [
        { job_id: "job1", name: "Binder", card_count: 49, created: "2026-01-02T00:00:00Z" },
        { job_id: "job2", name: "Trade Box", card_count: 120, created: "2026-01-01T00:00:00Z" }] } }),
      "GET /api/decks": () => ({ json: { decks: [] } }),
      "GET /api/forge/formats": () => ({ json: { formats: [
        { key: "commander", name: "Commander", commander: true, deck_size: 100 },
        { key: "modern", name: "Modern", commander: false, deck_size: 60 },
        { key: "casual", name: "Casual", commander: false, deck_size: 60 }] } }),
      "GET /api/ai/status": () => ({ json: { available: false, models: [] } }),
      "GET /api/forge/commanders/job1": () => ({ json: { commanders: [
        { id: "id-krenko", name: "Krenko, Mob Boss", image_url: "" }], total: 1 } }),
      "GET /api/forge/check/job1": (req) => reply(req),
      "POST /api/forge": (req) => {
        posts.push(req.body);
        return { status: 400, json: { detail: "Stop here." } };
      },
    },
  });
  document = app.document;
  window = app.window;
});

const $ = (sel) => document.querySelector(sel);
const checks = () => app.fetchLog.filter((r) => r.path === "/api/forge/check/job1");
const lastCheck = () => checks().at(-1);
const fire = (el, type = "change") => el.dispatchEvent(new window.Event(type, { bubbles: true }));
const pickFormat = (key) => {
  $("#forge-format").value = key;
  fire($("#forge-format"));
};
// Ask again with a new answer: a format change starts a new check.
async function recheck(answer) {
  reply = () => ({ json: answer });
  const before = checks().length;
  pickFormat("modern");
  pickFormat("commander");
  await app.until(() => checks().length >= before + 2);
  await app.until(() => $("#forge-format-note").textContent === answer.summary);
  await app.settle();
}

test("the setup says how many cards are legal and how big the deck is", async () => {
  await app.until(() => $("#forge-format-note").textContent === OK.summary);
  assert.equal($("#forge-format-note").hidden, false);
  assert.equal(lastCheck().query.get("format"), "commander");
  assert.equal(lastCheck().query.get("also"), null);
  assert.equal($("#forge-start").disabled, false);
  assert.equal($("#forge-start-note").hidden, true);
});

test("too few cards turn the Forge button off, with the reason next to it", async () => {
  await recheck(NO_COMMANDER);
  assert.equal($("#forge-start").disabled, true);
  assert.equal($("#forge-start-note").hidden, false);
  assert.equal($("#forge-start-note").textContent, NO_COMMANDER.problem);
  assert.equal($("#forge-start").getAttribute("aria-describedby"), "forge-start-note");
  assert.ok($("#forge-start-note").closest(".forge-actions"), "the reason sits next to the button");
  $("#forge-form").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
  await app.settle();
  assert.equal(posts.length, 0, "a blocked forge sends nothing");
  // A commander tile cannot lift this block: no card can be a commander.
  await app.until(() => document.querySelectorAll("#forge-commander-grid .forge-tile").length === 2);
  document.querySelectorAll("#forge-commander-grid .forge-tile")[1].click();
  assert.equal($("#forge-start").disabled, true);
});

test("a chosen commander lifts a block that a commander can fix", async () => {
  await recheck(TOO_FEW);
  await app.until(() => document.querySelectorAll("#forge-commander-grid .forge-tile").length === 2);
  const [agent, krenko] = document.querySelectorAll("#forge-commander-grid .forge-tile");
  agent.click();
  assert.equal($("#forge-start").disabled, true);
  assert.equal($("#forge-start-note").textContent, TOO_FEW.problem);
  krenko.click();
  assert.equal($("#forge-start").disabled, false);
  assert.equal($("#forge-start-note").hidden, true);
  $("#forge-form").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
  await app.until(() => posts.length === 1);
  assert.equal(posts[0].commander, "Krenko, Mob Boss");
  await app.until(() => !$("#forge-start").disabled);
  agent.click();
  assert.equal($("#forge-start").disabled, true);
});

test("the check reads the whole pool, free copies and the Casual options", async () => {
  await recheck(OK);
  const boxes = [...document.querySelectorAll("#forge-collections input")];
  boxes[1].checked = true;
  fire(boxes[1]);
  await app.until(() => lastCheck().query.get("also") === "job2");
  assert.equal(lastCheck().query.get("free_only"), null);
  $("#forge-free-only").checked = true;
  fire($("#forge-free-only"));
  await app.until(() => lastCheck().query.get("free_only") === "true");
  pickFormat("casual");
  await app.until(() => lastCheck().query.get("format") === "casual");
  assert.equal(lastCheck().query.get("deck_size"), "60");
  $("#forge-deck-size").value = "40";
  fire($("#forge-deck-size"));
  await app.until(() => lastCheck().query.get("deck_size") === "40");
  $("#forge-max-copies").value = "1";
  fire($("#forge-max-copies"));
  await app.until(() => lastCheck().query.get("max_copies") === "1");
  document.querySelector('.forge-color[data-color="B"]').click();
  await app.until(() => lastCheck().query.get("colors") === "B");
  // The other formats send no Casual options.
  pickFormat("modern");
  await app.until(() => lastCheck().query.get("format") === "modern");
  assert.equal(lastCheck().query.get("deck_size"), null);
  assert.equal(lastCheck().query.get("colors"), null);
  boxes[1].checked = false;
  fire(boxes[1]);
  $("#forge-free-only").checked = false;
  fire($("#forge-free-only"));
  pickFormat("commander");
  await app.until(() => lastCheck().query.get("format") === "commander" && !lastCheck().query.get("also"));
});

test("an old answer does not replace the answer to a newer check", async () => {
  let release;
  const slow = new Promise((resolve) => { release = resolve; });
  let calls = 0;
  reply = () => {
    calls += 1;
    return calls === 1 ? slow.then(() => ({ json: NO_COMMANDER })) : { json: OK };
  };
  pickFormat("modern");
  pickFormat("commander");
  await app.until(() => calls === 2);
  await app.until(() => $("#forge-format-note").textContent === OK.summary);
  release();
  await app.settle();
  await app.settle();
  assert.equal($("#forge-format-note").textContent, OK.summary);
  assert.equal($("#forge-start").disabled, false);
});

test("a check that fails leaves the Forge button on and says why", async () => {
  reply = () => ({ status: 404, json: { detail: "Collection not found" } });
  pickFormat("modern");
  await app.until(() => $("#forge-format-note").textContent === "Could not check the cards: Collection not found");
  assert.equal($("#forge-start").disabled, false);
  assert.equal($("#forge-start-note").hidden, true);
});
