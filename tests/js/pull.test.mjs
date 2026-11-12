import { test } from "node:test";
import assert from "node:assert/strict";
import { pullText } from "../../frontend/js/decks/pull.js";

test("the pull list text has one block per binder, then basics and missing cards", () => {
  const text = pullText({
    groups: [
      { collection: "Main box", binder: "Red binder", cards: [
        { name: "Card A", count: 2, set: "TST", number: "1", foil: "normal" }] },
      { collection: "Trade box", binder: "", cards: [
        { name: "Card B", count: 1, set: "", number: "", foil: "etched" }] },
    ],
    basics: [{ name: "Mountain", count: 18 }],
    missing: [{ name: "Card C", count: 1 }],
  });
  assert.equal(text, "Main box · Red binder\n2 Card A (TST 1)\n\nTrade box\n1 Card B etched\n\n"
    + "Basic lands\n18 Mountain\n\nNot owned\n1 Card C");
});
