import { test } from "node:test";
import assert from "node:assert/strict";
import {
  SETTINGS_KEY, ENGINE_ONLY, ASK_MODES, DEFAULTS, readSettings, writeSettings, chooseModel,
} from "../../frontend/js/shared/settings.js";

function fakeStorage(initial = {}) {
  const data = { ...initial };
  return {
    data,
    getItem: (k) => (k in data ? data[k] : null),
    setItem: (k, v) => { data[k] = String(v); },
  };
}

const throwing = {
  getItem() { throw new Error("blocked"); },
  setItem() { throw new Error("full"); },
};

const ai = { available: true, models: ["llama3:8b", "qwen3.5:9b"], default_model: "llama3:8b", recommended: "qwen3.5:9b" };

test("the constants have the agreed values", () => {
  assert.equal(SETTINGS_KEY, "grimoire.settings");
  assert.equal(ENGINE_ONLY, "none");
  assert.deepEqual(ASK_MODES, ["countdown", "wait", "never"]);
  assert.deepEqual(DEFAULTS, { model: "", askMode: "countdown" });
});

test("readSettings falls back per field", () => {
  const storage = fakeStorage({ [SETTINGS_KEY]: JSON.stringify({ model: "x", askMode: "bogus" }) });
  assert.deepEqual(readSettings(storage), { model: "x", askMode: "countdown" });
});

test("readSettings gives the defaults for bad JSON and an empty storage", () => {
  assert.deepEqual(readSettings(fakeStorage({ [SETTINGS_KEY]: "{nope" })), DEFAULTS);
  assert.deepEqual(readSettings(fakeStorage()), DEFAULTS);
  assert.deepEqual(readSettings(fakeStorage({ [SETTINGS_KEY]: "[1]" })), DEFAULTS);
});

test("readSettings survives a throwing storage", () => {
  assert.deepEqual(readSettings(throwing), DEFAULTS);
});

test("writeSettings merges a patch and returns the settings", () => {
  const storage = fakeStorage({ [SETTINGS_KEY]: JSON.stringify({ model: "x", askMode: "wait" }) });
  const result = writeSettings({ askMode: "never" }, storage);
  assert.deepEqual(result, { model: "x", askMode: "never" });
  assert.deepEqual(JSON.parse(storage.data[SETTINGS_KEY]), { model: "x", askMode: "never" });
});

test("writeSettings ignores a throwing storage", () => {
  assert.deepEqual(writeSettings({ model: "y" }, throwing), { model: "y", askMode: "countdown" });
});

test("chooseModel keeps an installed model", () => {
  assert.equal(chooseModel(ai, "llama3:8b"), "llama3:8b");
});

test("chooseModel keeps engine-only", () => {
  assert.equal(chooseModel(ai, ENGINE_ONLY), ENGINE_ONLY);
});

test("chooseModel falls back when the model is gone", () => {
  assert.equal(chooseModel(ai, "gone:1b"), "qwen3.5:9b");
  assert.equal(chooseModel(ai, ""), "qwen3.5:9b");
});

test("chooseModel gives engine-only when only other models are installed", () => {
  const other = { ...ai, models: ["llama3:8b", "big:70b"], default_model: "big:70b" };
  assert.equal(chooseModel(other, ""), ENGINE_ONLY);
  assert.equal(chooseModel(other, "gone:1b"), ENGINE_ONLY);
});

test("chooseModel gives engine-only with no models", () => {
  assert.equal(chooseModel({ available: false, models: [], default_model: null, recommended: "qwen3.5:9b" }, "x"), ENGINE_ONLY);
  assert.equal(chooseModel({ available: false, models: ["a"] }, "a"), ENGINE_ONLY);
});
