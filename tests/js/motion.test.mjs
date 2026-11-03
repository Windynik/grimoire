// The motion module: durations, easing, reduced motion, and a safe animate().
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { DURATION, EASE, animate, onReducedMotionChange, reducedMotion } from "../../frontend/js/shared/motion.js";

const TOKENS = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "frontend", "css", "tokens.css");

// A window whose matchMedia answers the reduced-motion query and records listeners.
function fakeWin(reduced) {
  const listeners = new Set();
  const query = {
    get matches() { return reduced; },
    addEventListener(type, fn) { if (type === "change") listeners.add(fn); },
    removeEventListener(type, fn) { if (type === "change") listeners.delete(fn); },
  };
  return {
    listeners,
    matchMedia: (q) => (/prefers-reduced-motion: reduce/.test(q) ? query : { matches: false }),
    set(value) {
      reduced = value;
      listeners.forEach((fn) => fn({ matches: value }));
    },
  };
}

test("animate skips el.animate under reduced motion", async () => {
  const el = { animate: () => assert.fail("animated") };
  await animate(el, [{ opacity: 0 }, { opacity: 1 }], { duration: "base", win: fakeWin(true) });
});

test("animate resolves when el.animate is missing", async () => {
  await animate({}, [{ opacity: 0 }, { opacity: 1 }], { win: fakeWin(false) });
});

test("animate resolves on finished and maps the duration key", async () => {
  const calls = [];
  const el = {
    animate(keyframes, timing) {
      calls.push(timing);
      return { finished: Promise.resolve() };
    },
  };
  await animate(el, [{ opacity: 0 }, { opacity: 1 }], { duration: "slow", fill: "forwards", win: fakeWin(false) });
  await animate(el, [{ opacity: 0 }, { opacity: 1 }], { duration: 380, easing: "inOut", win: fakeWin(false) });
  assert.deepEqual(calls, [
    { duration: 600, easing: EASE.out, fill: "forwards" },
    { duration: 380, easing: EASE.inOut },
  ]);
});

test("animate resolves when the animation is cancelled", async () => {
  const abort = Object.assign(new Error("The animation was cancelled."), { name: "AbortError" });
  const el = { animate: () => ({ finished: Promise.reject(abort) }) };
  await animate(el, [{ opacity: 0 }, { opacity: 1 }], { duration: "fast", win: fakeWin(false) });
});

test("animate rejects on other errors", async () => {
  const el = { animate: () => ({ finished: Promise.reject(new TypeError("bad keyframes")) }) };
  await assert.rejects(animate(el, [], { win: fakeWin(false) }), TypeError);
});

test("animate refuses an unknown duration key", async () => {
  const el = { animate: () => assert.fail("animated") };
  await assert.rejects(animate(el, [], { duration: "slowest", win: fakeWin(false) }), RangeError);
});

test("duration keys map to the tokens", () => assert.deepEqual(DURATION, { fast: 150, base: 250, slow: 600 }));

test("DURATION and EASE match tokens.css", () => {
  const css = readFileSync(TOKENS, "utf8");
  const token = (name) => css.match(new RegExp(`${name}:\\s*([^;]+);`))[1].trim();
  assert.equal(`${DURATION.fast}ms`, token("--dur-fast"));
  assert.equal(`${DURATION.base}ms`, token("--dur-base"));
  assert.equal(`${DURATION.slow}ms`, token("--dur-slow"));
  assert.equal(EASE.out, token("--ease-out"));
  assert.equal(EASE.inOut, token("--ease-in-out"));
});

test("reducedMotion reads the media query", () => {
  assert.equal(reducedMotion(fakeWin(true)), true);
  assert.equal(reducedMotion(fakeWin(false)), false);
  assert.equal(reducedMotion({}), false);
  assert.equal(reducedMotion(undefined), false);
});

test("onReducedMotionChange reports changes until unsubscribed", () => {
  const win = fakeWin(false);
  const seen = [];
  const off = onReducedMotionChange((reduced) => seen.push(reduced), win);
  win.set(true);
  win.set(false);
  off();
  win.set(true);
  assert.deepEqual(seen, [true, false]);
  assert.equal(win.listeners.size, 0);
  assert.equal(typeof onReducedMotionChange(() => {}, {}), "function");
});
