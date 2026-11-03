// The remembered state of the Vault screen (frontend/js/collection/state.js).
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  defaultState, loadState, saveState, normalizeState, storageKey,
} from "../../frontend/js/collection/state.js";

function memory(initial = {}) {
  const data = new Map(Object.entries(initial));
  return {
    data,
    getItem: (key) => (data.has(key) ? data.get(key) : null),
    setItem: (key, value) => data.set(key, String(value)),
    removeItem: (key) => data.delete(key),
  };
}

const blocked = {
  getItem() { throw new Error("blocked"); },
  setItem() { throw new Error("blocked"); },
  removeItem() { throw new Error("blocked"); },
};

test("a missing key gives the defaults", () => {
  const state = loadState("job1", {}, memory());
  assert.deepEqual(state, defaultState());
  assert.equal(state.sort, "price");
  assert.equal(state.view, "grid");
  assert.equal(state.size, "M");
  assert.deepEqual(state.colors, []);
});

test("saveState and loadState keep the search, filters, sort, view, and size", () => {
  const store = memory();
  const state = {
    ...defaultState(), q: "t:dragon", colors: ["U", "M"], rarity: ["rare"], type: ["Creature"],
    mv: ["2", "7+"], format: ["modern"], set: ["neo"], price: 5, foil: true, dupes: true,
    sort: "name", view: "list", size: "L",
  };
  saveState("job1", state, store);
  assert.ok(store.data.has(storageKey("job1")));
  assert.deepEqual(loadState("job1", {}, store), state);
  // Each source has its own key.
  assert.deepEqual(loadState("job2", {}, store), defaultState());
});

test("invalid JSON falls back to the defaults", () => {
  const store = memory({ [storageKey("job1")]: "{not json" });
  assert.deepEqual(loadState("job1", {}, store), defaultState());
  const array = memory({ [storageKey("job1")]: "[1,2]" });
  assert.deepEqual(loadState("job1", {}, array), defaultState());
});

test("stale or unknown values fall back field by field", () => {
  const raw = {
    q: 42, colors: ["U", "X", "U", 3], rarity: ["rare", "special"], type: ["Creature", "Tribal"],
    mv: ["3", "9", 2], format: ["modern", "<b>"], set: ["neo", "not a set!"], price: 7,
    foil: "yes", dupes: 1, sort: "random", view: "sets", size: "XL", extra: "dropped",
  };
  const state = normalizeState(raw);
  assert.equal(state.q, "");
  assert.deepEqual(state.colors, ["U"]);
  assert.deepEqual(state.rarity, ["rare"]);
  assert.deepEqual(state.type, ["Creature"]);
  assert.deepEqual(state.mv, ["3"]);
  assert.deepEqual(state.format, ["modern"]);
  assert.deepEqual(state.set, ["neo"]);
  assert.equal(state.price, null);
  assert.equal(state.foil, false);
  assert.equal(state.dupes, false);
  assert.equal(state.sort, "price");
  assert.equal(state.view, "grid");
  assert.equal(state.size, "M");
  assert.equal("extra" in state, false);
});

test("the archive keeps one value per filter and drops the collection-only filters", () => {
  const raw = {
    ...defaultState(), colors: ["U", "M", "B"], rarity: ["rare", "mythic"], type: ["Land"],
    mv: ["2", "3"], set: ["neo"], foil: true, dupes: true, sort: "edhrec",
  };
  const state = normalizeState(raw, { archive: true });
  assert.deepEqual(state.colors, ["U"]);
  assert.deepEqual(state.rarity, ["rare"]);
  assert.deepEqual(state.type, ["Land"]);
  assert.deepEqual(state.mv, ["2"]);
  assert.deepEqual(state.set, []);
  assert.equal(state.foil, false);
  assert.equal(state.dupes, false);
  assert.equal(state.sort, "price", "the archive sorts by name or price only");
  // Multicolor has no archive filter.
  assert.deepEqual(normalizeState({ colors: ["M"] }, { archive: true }).colors, []);
});

test("a blocked storage gives the defaults and does not throw", () => {
  assert.deepEqual(loadState("job1", {}, blocked), defaultState());
  assert.doesNotThrow(() => saveState("job1", defaultState(), blocked));
});

test("a long search text is cut, and the saved state is a copy", () => {
  const state = normalizeState({ q: "x".repeat(500) });
  assert.equal(state.q.length, 200);
  const base = defaultState();
  base.colors.push("W");
  assert.deepEqual(defaultState().colors, [], "defaultState returns a fresh object");
});
