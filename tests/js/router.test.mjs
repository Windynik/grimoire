import { test } from "node:test";
import assert from "node:assert/strict";
import { NAV_PARENT, SCREENS, parseHash } from "../../frontend/js/app/router.js";

test("parseHash maps every route", () => {
  assert.deepEqual(parseHash(""), { screen: "home", params: {} });
  assert.deepEqual(parseHash("#home"), { screen: "home", params: {} });
  assert.deepEqual(parseHash("#deck/abc_1"), { screen: "decks", params: { deckId: "abc_1" } });
  assert.deepEqual(parseHash("#import"), { screen: "import", params: {} });
  assert.deepEqual(parseHash("#welcome"), { screen: "welcome", params: {} });
  assert.deepEqual(parseHash("#deck/../x"), { screen: "home", params: {} });
  assert.deepEqual(parseHash("#nope"), { screen: "home", params: {} });
});

test("parseHash maps each screen name to its screen", () => {
  for (const screen of SCREENS) assert.deepEqual(parseHash(`#${screen}`), { screen, params: {} });
});

test("parseHash refuses a deck id with other characters", () => {
  assert.deepEqual(parseHash("#deck/"), { screen: "home", params: {} });
  assert.deepEqual(parseHash("#deck/a b"), { screen: "home", params: {} });
  assert.deepEqual(parseHash("#deck/a/b"), { screen: "home", params: {} });
});

test("the screen list and the nav parents", () => {
  assert.deepEqual(SCREENS, ["home", "collection", "import", "forge", "decks", "settings", "welcome"]);
  assert.deepEqual(NAV_PARENT, { import: "collection", welcome: "home" });
});
