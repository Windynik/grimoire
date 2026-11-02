import { test } from "node:test";
import assert from "node:assert/strict";
import { isRecommended, pickModel } from "../../frontend/js/shared/models.js";

const ai = (extra) => ({ available: true, models: ["a:1b", "rec:9b"], default_model: "a:1b", recommended: "rec", ...extra });

test("the recommended model wins when installed", () => {
  assert.equal(pickModel(ai({ models: ["a:1b", "rec"], recommended: "rec" })), "rec");
});

test("the recommended model matches a name:tag prefix", () => {
  assert.equal(isRecommended(ai(), "rec:9b"), true);
  assert.equal(isRecommended(ai(), "recx:9b"), false);
  assert.equal(pickModel(ai()), "rec:9b");
});

test("the default model is the fallback", () => {
  assert.equal(pickModel(ai({ models: ["a:1b"] })), "a:1b");
});

test("no model when Ollama is not available", () => {
  assert.equal(pickModel(ai({ available: false })), null);
});
