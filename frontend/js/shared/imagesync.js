// The background image download. One page runs at most one stream.
//
// main.js starts it at app start. Settings shows its live progress.
// A failure never throws to the caller. It sets state.error and logs to the console.

import { getJSON } from "./http.js";
import { readSettings } from "./settings.js";
import { readSSE } from "./sse.js";

const IDLE = { running: false, phase: "small", done: 0, total: 0, failed: 0, skipped: 0, error: null };

let state = { ...IDLE };
let current = null;
const listeners = new Set();

/** A copy of the current state of the download. */
export function imageSyncState() {
  return { ...state };
}

/** Call fn(state) on every change. Returns a function that stops the calls. */
export function onImageSync(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function update(patch) {
  state = { ...state, ...patch };
  for (const fn of [...listeners]) {
    try {
      fn(imageSyncState());
    } catch (error) {
      console.error("An image sync listener failed:", error);
    }
  }
}

let sawDone = false;

function onEvent(event) {
  if (event.type === "progress") {
    update({ phase: event.phase, done: event.done, total: event.total, failed: event.failed });
  } else if (event.type === "done") {
    sawDone = true;
    update({
      phase: event.phase, done: event.done, total: event.total, failed: event.failed,
      skipped: event.skipped || 0, error: event.busy ? "busy" : null,
    });
  }
}

async function run() {
  sawDone = false;
  update({ ...IDLE, running: true });
  try {
    const response = await fetch("/api/images/prefetch", { method: "POST" });
    if (response.status === 409) {
      update({ error: "busy" });
    } else if (!response.ok) {
      throw new Error(`The image download failed (${response.status}).`);
    } else {
      await readSSE(response, onEvent);
      // A stream that ends without a done event was cut off. It is not a success.
      if (!sawDone) update({ error: "ended" });
    }
  } catch (error) {
    console.warn("The image download stopped:", error);
    update({ error: error.message || "failed" });
  } finally {
    current = null;
    update({ running: false });
  }
}

/** Start the download. Returns the run that is already going when there is one. */
export function startImageSync() {
  if (!current) current = run();
  return current;
}

/**
 * Start the download when the owner allows it and an owned image is missing.
 * It is quiet. It never throws.
 */
export async function autoStartImageSync() {
  if (!readSettings().autoImages) return;
  try {
    const s = await getJSON("/images/status");
    if (s.owned_small >= s.owned_total && s.owned_normal >= s.owned_total) return;
    await startImageSync();
  } catch (error) {
    console.warn("Could not start the image download:", error);
  }
}
