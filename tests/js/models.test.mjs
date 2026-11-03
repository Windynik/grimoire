import { test } from "node:test";
import assert from "node:assert/strict";
import { isRecommended } from "../../frontend/js/shared/models.js";

const ai = { available: true, models: ["a:1b", "rec:9b"], default_model: "a:1b", recommended: "rec" };

test("the recommended model matches by exact name or name:tag prefix", () => {
  assert.equal(isRecommended(ai, "rec"), true);
  assert.equal(isRecommended(ai, "rec:9b"), true);
  assert.equal(isRecommended(ai, "recx:9b"), false);
  assert.equal(isRecommended({ ...ai, recommended: null }, "rec"), false);
});
