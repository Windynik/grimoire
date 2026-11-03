// Card images: the local image URL of a card, the blur-up card image, and the
// background preload.
//
// The backend serves GET /api/images/{scryfall_id}/{face}?size=small|normal from
// its image store. A card without a valid id uses the raw URL of the index.
// The card name goes in with textContent only.

import { h } from "./dom.js";
import { reducedMotion } from "./motion.js";

// The id pattern of backend/core/image_store.py.
const ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const SIZES = new Set(["small", "normal"]);

const hasText = (value) => typeof value === "string" && value.trim() !== "";

/**
 * Return the URL of one face of a card image.
 *
 * @param {Object} card A card with scryfall_id, image_url and back_image_url.
 * @param {string} [face] "front" or "back".
 * @param {string} [size] "small" (146 × 204) or "normal" (488 × 680).
 * @returns {string} The local URL when the card has a valid id and an image for
 *   that face; else the raw URL of that face (the raw normal URL for a small
 *   image); else "".
 */
export function cardImage(card, face = "front", size = "normal") {
  if (!card) return "";
  const back = face === "back";
  const raw = back ? card.back_image_url : card.image_url;
  if (!hasText(raw)) return "";
  if (typeof card.scryfall_id === "string" && ID.test(card.scryfall_id) && SIZES.has(size)) {
    return `/api/images/${card.scryfall_id}/${back ? "back" : "front"}?size=${size}`;
  }
  return raw;
}

// The start function of each card image built with defer and not yet started.
const pending = new WeakMap();

// True when the image is in the browser cache and decoded enough to show.
const ready = (img) => Boolean(img.complete && img.naturalWidth > 0);

function layer(className, alt, priority) {
  const high = priority === "high";
  // The loading attribute goes on before the src, so a lazy image waits.
  return h("img", {
    class: className, alt, decoding: "async",
    loading: high ? "eager" : "lazy", fetchpriority: high ? "high" : null,
  });
}

/**
 * Build a card image that loads in layers: a card-shaped placeholder with the
 * card name and a shimmer, then the small image blurred, then the sharp image.
 *
 * The wrapper takes these state classes: is-small (the blurred small image
 * shows), is-loaded (the sharp image shows), is-done (the fade ended; the lower
 * layers hide), is-error (the sharp image failed; the placeholder stays), and
 * no-fade (cached or reduced motion: the layers swap at once).
 *
 * @param {Object} card A card with name, scryfall_id, image_url and back_image_url.
 * @param {Object} [options]
 * @param {string} [options.face] "front" (default) or "back".
 * @param {string} [options.alt] Alternative text of the sharp image (default "").
 * @param {string} [options.className] More classes for the wrapper.
 * @param {string} [options.priority] "high" loads at once with a high fetch priority.
 * @param {string} [options.size] "normal" (default: small image, then normal image)
 *   or "small" (the small image only, not blurred).
 * @param {boolean} [options.defer] true: the images get no src until loadCardImg.
 *   The name placeholder shows at once.
 * @returns {HTMLSpanElement}
 */
export function cardImg(card, options = {}) {
  const {
    face = "front", alt = "", className = "", priority, size = "normal", defer = false,
  } = options;
  const small = size === "small";
  const sharpUrl = cardImage(card, face, small ? "small" : "normal");
  const blurUrl = small ? "" : cardImage(card, face, "small");
  const name = card && card.name ? String(card.name) : "";

  const wrap = h("span", {
    class: `card-img ${className}`.trim(), "data-size": small ? "small" : "normal",
  }, h("span", { class: "card-img-placeholder", "aria-hidden": "true" },
    h("span", { class: "card-img-shimmer" }),
    h("span", { class: "card-img-name", text: name })));
  if (reducedMotion()) wrap.classList.add("no-fade");
  if (!sharpUrl) {
    wrap.classList.add("is-error");
    return wrap;
  }

  // A raw URL serves both sizes, so the blurred layer would load the same file.
  const blur = blurUrl && blurUrl !== sharpUrl ? layer("card-img-blur", "", priority) : null;
  const sharp = layer("card-img-sharp", alt, priority);
  if (blur) {
    blur.setAttribute("aria-hidden", "true");
    blur.addEventListener("load", () => wrap.classList.add("is-small"));
    wrap.append(blur);
  }
  wrap.append(sharp);

  const done = () => wrap.classList.add("is-done");
  const show = (instant) => {
    if (instant) wrap.classList.add("no-fade");
    wrap.classList.remove("is-error");
    wrap.classList.add("is-loaded");
    if (wrap.classList.contains("no-fade")) done();
    else sharp.addEventListener("transitionend", done, { once: true });
  };
  sharp.addEventListener("load", () => show(false));
  sharp.addEventListener("error", () => wrap.classList.add("is-error"));

  // A cached image shows at once, with no fade. The second check runs after
  // the caller inserts the wrapper, before the first paint.
  const cached = () => {
    if (!wrap.classList.contains("is-loaded") && ready(sharp)) show(true);
  };
  const start = () => {
    if (blur) blur.setAttribute("src", blurUrl);
    sharp.setAttribute("src", sharpUrl);
    cached();
    if (typeof requestAnimationFrame === "function") requestAnimationFrame(cached);
  };
  if (defer) pending.set(wrap, start);
  else start();
  return wrap;
}

/** Start the downloads of a card image that cardImg built with defer. */
export function loadCardImg(wrap) {
  const start = wrap && pending.get(wrap);
  if (!start) return;
  pending.delete(wrap);
  start();
}

/** True when a card image built with defer did not start. */
export function isDeferred(wrap) {
  return Boolean(wrap && pending.has(wrap));
}

/**
 * Stop a card image for good: remove the src of its images, which aborts an
 * unfinished download. A deferred card image does not start after this.
 */
export function stopCardImg(wrap) {
  if (!wrap) return;
  pending.delete(wrap);
  wrap.querySelectorAll("img").forEach((img) => img.removeAttribute("src"));
}

/**
 * Load images in the background, at most limit at a time.
 *
 * @param {string[]} urls Empty and repeated URLs are skipped.
 * @param {number} [limit] Most images that load at the same time.
 * @returns {function(): void} Stops the images that did not start.
 */
export function preload(urls, limit = 6) {
  const queue = [...new Set(urls.filter(Boolean))];
  let active = 0;
  let stopped = false;
  const next = () => {
    while (!stopped && active < limit && queue.length) {
      const img = new window.Image();
      active += 1;
      const settle = () => {
        img.onload = null;
        img.onerror = null;
        active -= 1;
        next();
      };
      img.onload = settle;
      img.onerror = settle;
      img.decoding = "async";
      img.src = queue.shift();
    }
  };
  next();
  return () => {
    stopped = true;
    queue.length = 0;
  };
}
