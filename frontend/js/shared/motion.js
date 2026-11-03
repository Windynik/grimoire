// Motion system: the one place in the frontend that animates elements or reads
// the reduced-motion preference. The values match the tokens in css/tokens.css.

const QUERY = "(prefers-reduced-motion: reduce)";

export const DURATION = Object.freeze({ fast: 150, base: 250, slow: 600 });

export const EASE = Object.freeze({
  out: "cubic-bezier(0.2, 0.8, 0.2, 1)",
  inOut: "cubic-bezier(0.65, 0, 0.35, 1)",
});

function query(win) {
  return win && typeof win.matchMedia === "function" ? win.matchMedia(QUERY) : null;
}

/** True when the owner asks for reduced motion. */
export function reducedMotion(win = globalThis.window) {
  const media = query(win);
  return Boolean(media && media.matches);
}

/**
 * Call fn(reduced) each time the reduced-motion preference changes.
 * Returns the unsubscribe function.
 */
export function onReducedMotionChange(fn, win = globalThis.window) {
  const media = query(win);
  if (!media) return () => {};
  const handler = () => fn(Boolean(media.matches));
  if (typeof media.addEventListener === "function") {
    media.addEventListener("change", handler);
    return () => media.removeEventListener("change", handler);
  }
  if (typeof media.addListener === "function") {
    media.addListener(handler);
    return () => media.removeListener(handler);
  }
  return () => {};
}

function toDuration(value) {
  if (typeof value === "number") return value;
  if (Object.prototype.hasOwnProperty.call(DURATION, value)) return DURATION[value];
  throw new RangeError(`Unknown duration: ${value}`);
}

/**
 * Animate el with the Web Animations API. The promise resolves when the
 * animation ends or is cancelled. Under reduced motion, or without el.animate,
 * it resolves at once and el does not move.
 *
 * options.duration: a DURATION key or a number of milliseconds (default "base").
 * options.easing: an EASE key or a CSS easing (default EASE.out).
 * options.win: the window to ask about reduced motion (default window).
 * Other options go to el.animate unchanged.
 */
export async function animate(el, keyframes, options = {}) {
  const { win = globalThis.window, duration = "base", easing, ...rest } = options;
  const ms = toDuration(duration);
  if (!el || typeof el.animate !== "function" || reducedMotion(win)) return;
  const timing = { duration: ms, easing: EASE[easing] || easing || EASE.out, ...rest };
  try {
    await el.animate(keyframes, timing).finished;
  } catch (error) {
    if (!error || error.name !== "AbortError") throw error;
  }
}
