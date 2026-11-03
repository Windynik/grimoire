// Unit tests: the local image URL of a card, and the shimmer CSS of the loading animation.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { cardImage } from "../../frontend/js/shared/images.js";

const CSS_DIR = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "frontend", "css");
const css = (name) => readFileSync(join(CSS_DIR, name), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");

// Synthetic test ids and URLs.
const ID = "0000000a-0000-4000-8000-00000000000a";
const card = {
  scryfall_id: ID,
  name: "Test Card",
  image_url: "https://cards.example/normal/front/a.jpg",
  back_image_url: "https://cards.example/normal/back/a.jpg",
};

test("cardImage gives the local front image", () => {
  assert.equal(cardImage(card), `/api/images/${ID}/front?size=normal`);
  assert.equal(cardImage(card, "front", "small"), `/api/images/${ID}/front?size=small`);
});

test("cardImage gives the local back image", () => {
  assert.equal(cardImage(card, "back"), `/api/images/${ID}/back?size=normal`);
  assert.equal(cardImage(card, "back", "small"), `/api/images/${ID}/back?size=small`);
});

test("cardImage falls back to the raw URL without an id", () => {
  const noId = { ...card, scryfall_id: undefined };
  assert.equal(cardImage(noId), card.image_url);
  assert.equal(cardImage(noId, "back"), card.back_image_url);
  // A small image has no raw URL of its own: the raw normal URL stands in.
  assert.equal(cardImage(noId, "front", "small"), card.image_url);
});

test("cardImage falls back to the raw URL for a bad id", () => {
  for (const bad of ["basic:Island", "../../etc", ID.toUpperCase(), `${ID}x`, 42, null]) {
    assert.equal(cardImage({ ...card, scryfall_id: bad }), card.image_url, String(bad));
  }
});

test("cardImage gives no URL for a face without an image", () => {
  assert.equal(cardImage({ ...card, back_image_url: "" }, "back"), "");
  assert.equal(cardImage({ scryfall_id: ID, name: "One face", image_url: card.image_url }, "back"), "");
  assert.equal(cardImage({ ...card, image_url: "  " }), "");
  assert.equal(cardImage(null), "");
  assert.equal(cardImage(undefined, "back", "small"), "");
});

test("the shimmer moves a gradient layer with transform only", () => {
  const base = css("base.css");
  const frames = base.match(/@keyframes\s+card-img-shimmer\s*\{([\s\S]*?\}\s*)\}/);
  assert.ok(frames, "base.css has @keyframes card-img-shimmer");
  const props = [...frames[1].matchAll(/([-\w]+)\s*:/g)].map((m) => m[1]);
  assert.ok(props.length > 0);
  for (const prop of props) assert.equal(prop, "transform", `the shimmer animates ${prop}`);
  const rule = base.match(/\.card-img-shimmer\s*\{([^}]*)\}/);
  assert.ok(rule, "base.css styles .card-img-shimmer");
  assert.match(rule[1], /animation:\s*card-img-shimmer\s+calc\(var\(--dur-slow\)[^;]*\)\s+linear\s+infinite/);
  for (const [, selector, body] of base.matchAll(/([^{}]*card-img[^{}]*)\{([^}]*)\}/g)) {
    assert.doesNotMatch(body, /background-position/, selector.trim());
  }
});

test("reduced motion turns the shimmer off", () => {
  const tokens = css("tokens.css");
  const block = tokens.match(/@media\s*\(\s*prefers-reduced-motion:\s*reduce\s*\)\s*\{([\s\S]*)\}/);
  assert.ok(block);
  assert.match(block[1], /\.card-img-shimmer\s*\{[^}]*animation:\s*none/);
});

test("the shimmer band color is a token", () => {
  const rule = css("base.css").match(/\.card-img-shimmer\s*\{([^}]*)\}/);
  assert.match(rule[1], /var\(--shimmer-band\)/);
  assert.doesNotMatch(rule[1], /rgba\(/);
  assert.match(css("tokens.css"), /--shimmer-band:\s*rgba\(/);
});
