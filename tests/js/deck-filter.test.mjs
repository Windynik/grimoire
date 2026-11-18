// The search, sort and format filter of the deck list.
import { test } from "node:test";
import assert from "node:assert/strict";
import { filterDecks, fold, formatsOf, sortDecks } from "../../frontend/js/decks/filter.js";

const decks = [
  { id: "a", name: "Koma: Artifacts", format: "commander", commander: "Koma, Cosmos Serpent",
    count: 100, price: 310.5, updated: "2026-11-01T10:00:00" },
  { id: "b", name: "Artifacts (Standard)", format: "standard", commander: null,
    count: 60, price: null, updated: "2026-11-03T10:00:00" },
  { id: "c", name: "Éowyn: Enchantress & Voltron", format: "commander", commander: "Éowyn, Fearless Knight",
    count: 99, price: 42, updated: "2026-11-02T10:00:00" },
  { id: "d", name: "Koma: Artifacts", format: "commander", commander: { name: "Koma, Cosmos Serpent" },
    count: 100, price: 0, updated: "2026-10-30T10:00:00" },
];
const ids = (list) => list.map((d) => d.id);

test("fold drops the case and the accents", () => {
  assert.equal(fold("Éowyn ÆTHER Lórien"), "eowyn æther lorien");
  assert.equal(fold(null), "");
});

test("the search matches the name and the commander, without case or accents", () => {
  assert.deepEqual(ids(filterDecks(decks, { q: "KOMA" })), ["a", "d"]);
  assert.deepEqual(ids(filterDecks(decks, { q: "eowyn" })), ["c"]);
  assert.deepEqual(ids(filterDecks(decks, { q: "fearless" })), ["c"], "the commander, not only the name");
  assert.deepEqual(ids(filterDecks(decks, { q: "artifacts standard" })), ["b"], "every word must match");
  assert.deepEqual(ids(filterDecks(decks, { q: "  " })), ["a", "b", "c", "d"]);
  assert.deepEqual(filterDecks(decks, { q: "zzz" }), []);
  assert.deepEqual(filterDecks([], { q: "koma" }), []);
});

test("the format filter keeps one format, and an empty key keeps all", () => {
  assert.deepEqual(ids(filterDecks(decks, { format: "standard" })), ["b"]);
  assert.deepEqual(ids(filterDecks(decks, { format: "commander", q: "koma" })), ["a", "d"]);
  assert.deepEqual(ids(filterDecks(decks, { format: "" })), ["a", "b", "c", "d"]);
});

test("the sorts: last change, name, price and cards", () => {
  assert.deepEqual(ids(sortDecks(decks, "updated")), ["b", "c", "a", "d"]);
  // Equal names keep the newest first.
  assert.deepEqual(ids(sortDecks(decks, "name")), ["b", "c", "a", "d"]);
  // The highest price first; a deck with no price goes last.
  assert.deepEqual(ids(sortDecks(decks, "price")), ["a", "c", "d", "b"]);
  assert.deepEqual(ids(sortDecks(decks, "cards")), ["a", "d", "c", "b"]);
  assert.deepEqual(ids(sortDecks(decks, "bogus")), ids(sortDecks(decks, "updated")));
  assert.deepEqual(sortDecks([], "name"), []);
  assert.equal(decks[0].id, "a", "the sort does not change its input");
});

test("formatsOf lists each format with a deck once", () => {
  assert.deepEqual(formatsOf(decks), ["commander", "standard"]);
  assert.deepEqual(formatsOf([]), []);
});
