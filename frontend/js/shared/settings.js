// The saved settings: the model and the question mode. They live in localStorage.
//
// A blocked or full storage does not stop the app: a read gives the defaults,
// and a write does nothing.

import { pickModel } from "./models.js";

export const SETTINGS_KEY = "grimoire.settings";
/** The model value that means "run the engine without AI". */
export const ENGINE_ONLY = "none";
export const ASK_MODES = ["countdown", "wait", "never"];
/** model "" means automatic. */
export const DEFAULTS = { model: "", askMode: "countdown" };

function parse(storage) {
  try {
    const data = JSON.parse(storage.getItem(SETTINGS_KEY));
    return data && typeof data === "object" && !Array.isArray(data) ? data : {};
  } catch (e) {
    return {};
  }
}

/** Read the settings. Each unknown or missing field gives its default. */
export function readSettings(storage = localStorage) {
  const data = parse(storage);
  return {
    model: typeof data.model === "string" ? data.model : DEFAULTS.model,
    askMode: ASK_MODES.includes(data.askMode) ? data.askMode : DEFAULTS.askMode,
  };
}

/** Merge a patch into the saved settings and return the result. */
export function writeSettings(patch, storage = localStorage) {
  const settings = { ...readSettings(storage), ...patch };
  try {
    storage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  } catch (e) {
    // The storage is blocked or full. The app continues without saving.
  }
  return settings;
}

/**
 * Choose the model for a run: the wanted one when it is engine-only or
 * installed, else the automatic pick, else engine-only.
 */
export function chooseModel(ai, wanted) {
  if (wanted === ENGINE_ONLY) return ENGINE_ONLY;
  const installed = ai && ai.available ? ai.models || [] : [];
  if (wanted && installed.includes(wanted)) return wanted;
  return pickModel(ai) || ENGINE_ONLY;
}
