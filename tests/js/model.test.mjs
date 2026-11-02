import { test } from "node:test";
import assert from "node:assert/strict";
import {
  applyOp, entryKey, groupEntries, History, issueSummary, manaValue, SaveQueue, SECTIONS,
  toEntryCard,
} from "../../frontend/js/decks/model.js";

const bolt = { scryfall_id: "bolt", name: "Lightning Bolt", cmc: 1, type_line: "Instant" };
const state0 = () => ({ sections: { main: [], sideboard: [], maybeboard: [] }, commander: null });

test("entryKey uses the id, or basic:name without one", () => {
  assert.equal(entryKey({ scryfall_id: "x", name: "A" }), "x");
  assert.equal(entryKey({ name: "Forest", basic: true }), "basic:Forest");
  assert.deepEqual(SECTIONS, ["main", "sideboard", "maybeboard"]);
});

test("applyOp add, inc, dec, remove never mutate", () => {
  const s0 = state0();
  const frozen = JSON.stringify(s0);
  const s1 = applyOp(s0, { type: "add", section: "main", card: bolt });
  assert.equal(JSON.stringify(s0), frozen);
  assert.equal(s1.sections.main[0].count, 1);
  const s2 = applyOp(s1, { type: "add", section: "main", card: bolt });
  assert.equal(s2.sections.main[0].count, 2);
  assert.equal(s1.sections.main[0].count, 1);
  const s3 = applyOp(s2, { type: "inc", section: "main", key: "bolt" });
  assert.equal(s3.sections.main[0].count, 3);
  const s4 = applyOp(s3, { type: "dec", section: "main", key: "bolt" });
  assert.equal(s4.sections.main[0].count, 2);
  assert.equal(s3.sections.main[0].count, 3);
  const s5 = applyOp(applyOp(s4, { type: "dec", section: "main", key: "bolt" }),
    { type: "dec", section: "main", key: "bolt" });
  assert.equal(s5.sections.main.length, 0);
  const s6 = applyOp(s4, { type: "remove", section: "main", key: "bolt" });
  assert.equal(s6.sections.main.length, 0);
  assert.equal(s4.sections.main.length, 1);
  assert.equal(s6.commander, null);
});

test("applyOp keeps the commander and ignores unknown keys", () => {
  const cmd = { scryfall_id: "c", name: "Cmdr" };
  const s = { ...state0(), commander: cmd };
  const next = applyOp(s, { type: "add", section: "main", card: bolt });
  assert.deepEqual(next.commander, cmd);
  const same = applyOp(next, { type: "inc", section: "main", key: "nope" });
  assert.deepEqual(same.sections, next.sections);
});

test("applyOp add treats a basic land by name", () => {
  const forest = { name: "Forest", basic: true };
  const s = applyOp(applyOp(state0(), { type: "add", section: "main", card: forest }),
    { type: "add", section: "main", card: forest });
  assert.equal(s.sections.main.length, 1);
  assert.equal(s.sections.main[0].count, 2);
});

test("move merges into an existing entry and moves part of a stack", () => {
  let s = state0();
  for (let i = 0; i < 3; i++) s = applyOp(s, { type: "add", section: "main", card: bolt });
  s = applyOp(s, { type: "add", section: "sideboard", card: bolt });
  const part = applyOp(s, { type: "move", from: "main", to: "sideboard", key: "bolt", count: 2 });
  assert.equal(part.sections.main[0].count, 1);
  assert.equal(part.sections.sideboard.length, 1);
  assert.equal(part.sections.sideboard[0].count, 3);
  assert.equal(s.sections.main[0].count, 3);
  const all = applyOp(s, { type: "move", from: "main", to: "maybeboard", key: "bolt" });
  assert.equal(all.sections.main.length, 0);
  assert.equal(all.sections.maybeboard[0].count, 3);
  const over = applyOp(s, { type: "move", from: "main", to: "maybeboard", key: "bolt", count: 9 });
  assert.equal(over.sections.main.length, 0);
  assert.equal(over.sections.maybeboard[0].count, 3);
});

test("replace swaps the sections and keeps the commander", () => {
  const s = { ...state0(), commander: { scryfall_id: "c", name: "C" } };
  const sections = { main: [{ scryfall_id: "a", name: "A", count: 1 }], sideboard: [], maybeboard: [] };
  const next = applyOp(s, { type: "replace", sections });
  assert.equal(next.sections.main[0].name, "A");
  assert.equal(next.commander.name, "C");
  sections.main[0].count = 9;
  assert.equal(next.sections.main[0].count, 1);
});

test("History undo and redo with a limit of 3", () => {
  const h = new History(3);
  const st = (n) => ({ sections: { main: [{ name: "n" + n, count: n }] }, commander: null });
  assert.equal(h.canUndo, false);
  assert.equal(h.undo(), null);
  [1, 2, 3, 4].forEach((n) => h.push(st(n)));
  assert.equal(h.undo().sections.main[0].count, 3);
  assert.equal(h.undo().sections.main[0].count, 2);
  assert.equal(h.undo(), null);
  assert.equal(h.canUndo, false);
  assert.equal(h.canRedo, true);
  assert.equal(h.redo().sections.main[0].count, 3);
  assert.equal(h.redo().sections.main[0].count, 4);
  assert.equal(h.redo(), null);
  h.undo();
  h.push(st(9));
  assert.equal(h.canRedo, false);
});

test("History stores deep copies", () => {
  const h = new History();
  const s = { sections: { main: [{ name: "a", count: 1 }] }, commander: null };
  h.push(s);
  h.push({ sections: { main: [] }, commander: null });
  s.sections.main[0].count = 5;
  const back = h.undo();
  assert.equal(back.sections.main[0].count, 1);
  back.sections.main[0].count = 7;
  h.redo();
  assert.equal(h.undo().sections.main[0].count, 1);
});

test("groupEntries by type uses the first front-face type in order", () => {
  const entries = [
    { name: "Golem", type_line: "Artifact Creature — Golem", cmc: 3 },
    { name: "Bolt", type_line: "Instant", cmc: 1 },
    { name: "Mdfc", type_line: "Creature — Elf // Land", cmc: 2 },
    { name: "Forest", type_line: "Basic Land — Forest", cmc: 0 },
    { name: "Mystery", type_line: "", cmc: 0 },
    { name: "Ankh", type_line: "Artifact", cmc: 1 },
    { name: "Aardvark", type_line: "Creature", cmc: 3, count: 2 },
  ];
  const groups = groupEntries(entries, "type");
  assert.deepEqual(groups.map((g) => g.title), ["Creature", "Instant", "Artifact", "Land", "Other"]);
  const creature = groups[0];
  assert.deepEqual(creature.entries.map((e) => e.name), ["Mdfc", "Aardvark", "Golem"]);
  assert.equal(creature.count, 1 + 2 + 1);
});

test("groupEntries by role falls back to analysis roles, then Other", () => {
  const entries = [
    { scryfall_id: "a", name: "A", role: "Ramp", cmc: 2 },
    { scryfall_id: "b", name: "B", cmc: 1 },
    { scryfall_id: "c", name: "C", cmc: 1 },
  ];
  const analysis = { b: { roles: ["Removal", "Ramp"] } };
  const groups = groupEntries(entries, "role", analysis);
  assert.deepEqual(groups.map((g) => g.title), ["Ramp", "Removal", "Other"]);
});

test("groupEntries by cmc puts lands first and 7+ last", () => {
  const entries = [
    { name: "Big", type_line: "Creature", cmc: 8 },
    { name: "Zero", type_line: "Artifact", cmc: 0 },
    { name: "Three", type_line: "Creature", cmc: 3 },
    { name: "Swamp", type_line: "Basic Land — Swamp", cmc: 0 },
    { name: "Seven", type_line: "Creature", cmc: 7 },
  ];
  const groups = groupEntries(entries, "cmc");
  assert.deepEqual(groups.map((g) => g.title), ["Lands", "0", "3", "7+"]);
  assert.deepEqual(groups[3].entries.map((e) => e.name), ["Seven", "Big"]);
});

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

// A send whose requests finish only when the test says so.
function controlledSend() {
  const sent = [];
  const gates = [];
  const opts = [];
  const send = (snap, option) => {
    sent.push(snap);
    opts.push(option);
    return new Promise((resolve) => gates.push(resolve));
  };
  return { sent, opts, gates, send };
}

test("saveQueue sends only the newest snapshot", async () => {
  const { sent, gates, send } = controlledSend();
  const q = new SaveQueue(send, 5);
  q.schedule("a");
  await wait(30);
  assert.deepEqual(sent, ["a"]);
  q.schedule("b");
  q.schedule("c");
  await wait(30);
  assert.deepEqual(sent, ["a"]);
  gates[0]();
  await wait(10);
  assert.deepEqual(sent, ["a", "c"]);
  gates[1]();
  await wait(5);
  assert.equal(q.inflight, null);
});

test("saveQueue flush waits for the request in flight, then sends the newest", async () => {
  const { sent, gates, send } = controlledSend();
  const q = new SaveQueue(send, 5);
  q.schedule("a");
  await wait(30);
  q.schedule("b");
  q.schedule("c");
  let done = false;
  const flushed = q.flush().then(() => { done = true; });
  await wait(20);
  assert.deepEqual(sent, ["a"]);
  assert.equal(done, false);
  gates[0]();
  await wait(10);
  assert.deepEqual(sent, ["a", "c"]);
  assert.equal(done, false);
  gates[1]();
  await flushed;
  assert.equal(done, true);
  assert.equal(q.inflight, null);
});

test("saveQueue flush with nothing pending waits for the request in flight", async () => {
  const { gates, send } = controlledSend();
  const q = new SaveQueue(send, 5);
  q.schedule("a");
  await wait(30);
  let done = false;
  const flushed = q.flush().then(() => { done = true; });
  await wait(10);
  assert.equal(done, false);
  gates[0]();
  await flushed;
  assert.equal(done, true);
});

test("saveQueue flush closing sends at once with keepalive and does not wait", async () => {
  const { sent, opts, gates, send } = controlledSend();
  const q = new SaveQueue(send, 10000);
  q.schedule("x");
  q.schedule("y");
  assert.equal(sent.length, 0);
  const first = q.flush({ closing: true });
  assert.deepEqual(sent, ["y"]);
  assert.equal(opts[0].keepalive, true);
  gates[0]();
  await first;
  await q.flush({ closing: true });
  assert.equal(sent.length, 1);
  // closing while a request is in flight does not wait for it
  q.schedule("a");
  const second = q.flush({ closing: true });
  q.schedule("b");
  q.flush({ closing: true });
  assert.deepEqual(sent, ["y", "a", "b"]);
  gates[1]();
  gates[2]();
  await second;
});

test("saveQueue reports a send error and keeps going", async () => {
  const errors = [];
  const sent = [];
  const send = async (snap) => {
    sent.push(snap);
    if (snap === "bad") throw new Error("boom");
  };
  const q = new SaveQueue(send, 5);
  q.onError = (e) => errors.push(e.message);
  q.schedule("bad");
  await wait(30);
  assert.deepEqual(errors, ["boom"]);
  q.schedule("good");
  await q.flush();
  assert.deepEqual(sent, ["bad", "good"]);
  assert.equal(q.inflight, null);
});

test("set and remove commander ops", () => {
  const rhys = {
    scryfall_id: "rhys", name: "Rhys", count: 2, basic: false, role: "core", reason: "r",
    type_line: "Legendary Creature — Elf", image_url: "art",
  };
  const s0 = { ...state0(), sections: { main: [rhys, bolt], sideboard: [], maybeboard: [] } };
  const frozen = JSON.stringify(s0);
  const s1 = applyOp(s0, { type: "setCommander", key: "rhys" });
  assert.equal(JSON.stringify(s0), frozen);
  assert.deepEqual(Object.keys(s1).sort(), ["commander", "sections"]);
  assert.equal(s1.commander.scryfall_id, "rhys");
  assert.equal(s1.commander.image_url, "art");
  assert.equal(s1.commander.count, undefined);
  assert.equal(s1.sections.main[0].count, 1);

  // A second commander sends the first one back to main.
  const elf = { scryfall_id: "elf", name: "Elf", count: 1, basic: false };
  const s2 = applyOp(applyOp(s1, { type: "add", section: "main", card: elf }),
    { type: "setCommander", key: "elf" });
  assert.equal(s2.commander.scryfall_id, "elf");
  assert.equal(s2.sections.main.find((e) => e.scryfall_id === "rhys").count, 2);
  assert.equal(s2.sections.main.some((e) => e.scryfall_id === "elf"), false);

  // Remove: the commander returns to main as one copy; with no line it gets a new one.
  const s3 = applyOp(s1, { type: "clearCommander" });
  assert.equal(s3.commander, null);
  assert.equal(s3.sections.main.find((e) => e.scryfall_id === "rhys").count, 2);
  const solo = { ...state0(), commander: { scryfall_id: "c", name: "C" } };
  const s4 = applyOp(solo, { type: "clearCommander" });
  assert.equal(s4.commander, null);
  assert.deepEqual(s4.sections.main, [
    { scryfall_id: "c", name: "C", count: 1, basic: false, role: "", reason: "" },
  ]);

  // A key that is not in main, or no commander to clear, changes nothing.
  assert.deepEqual(applyOp(s0, { type: "setCommander", key: "nope" }), s0);
  assert.deepEqual(applyOp(s0, { type: "clearCommander" }), s0);
});

test("saveQueue sends a body scheduled during a closing flush after that request", async () => {
  const { sent, gates, send } = controlledSend();
  const q = new SaveQueue(send, 5);
  q.schedule("a");
  q.flush({ closing: true });
  assert.deepEqual(sent, ["a"]);
  q.schedule("b");
  await wait(30);
  // The timer fired during the request: the body waits for it.
  assert.deepEqual(sent, ["a"]);
  gates[0]();
  await wait(10);
  assert.deepEqual(sent, ["a", "b"]);
  gates[1]();
  await wait(5);
  assert.equal(q.inflight, null);
});

test("issueSummary counts entry issues by code", () => {
  const cards = {
    a: { owned: 0, issues: ["not_owned", "banned"], roles: [] },
    b: { owned: 1, issues: ["not_owned"], roles: [] },
    c: { owned: 1, issues: [], roles: [] },
    d: {},
  };
  assert.deepEqual(issueSummary(cards), { not_owned: 2, banned: 1 });
  assert.deepEqual(issueSummary(undefined), {});
});

test("manaValue sums a cost and reads the front face only", () => {
  assert.equal(manaValue("{2}{W}{W}"), 4);
  assert.equal(manaValue("{X}{R}"), 1);
  assert.equal(manaValue("{2/W}{G/U}"), 3);
  assert.equal(manaValue("{1}{U} // {3}{B}"), 2);
  assert.equal(manaValue(""), 0);
});

test("toEntryCard maps owned and archive results to the add shape", () => {
  const owned = {
    scryfall_id: "x", name: "Forest", mana_cost: "", type_line: "Basic Land — Forest",
    image_url: "i", quantity: "4", price: "0.10", oracle_text: "long", owned: true,
  };
  const card = toEntryCard(owned);
  assert.equal(card.scryfall_id, "x");
  assert.equal(card.basic, true);
  assert.equal(card.cmc, 0);
  assert.equal(card.price, 0.1);
  assert.equal("oracle_text" in card, false);
  assert.equal("quantity" in card, false);
  const bolt = toEntryCard({ id: "b", name: "Bolt", mana_cost: "{R}", type_line: "Instant" });
  assert.equal(bolt.scryfall_id, "b");
  assert.equal(bolt.basic, false);
  assert.equal(bolt.cmc, 1);
});
