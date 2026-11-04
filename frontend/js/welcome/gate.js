// The first-run gate: Home and the Vault send the owner to the welcome screen
// while there is no collection, unless the owner chose Skip there.
//
// This module builds no DOM. It reads the location hash and the session only.

import { parseHash, redirect } from "../app/router.js";
import { setWelcomeSkipped, welcomeSkipped } from "../shared/session.js";

/**
 * Send the owner to the welcome screen when there is no collection.
 *
 * @param {string} from The screen that asks: "home" or "collection".
 * @param {Array|null} collections The collection list; null when it did not load.
 * @returns {boolean} true when the welcome screen opens instead.
 */
export function gateFirstRun(from, collections) {
  if (!Array.isArray(collections)) return false;
  if (collections.length > 0) {
    // A collection exists: a later empty list starts the welcome again.
    setWelcomeSkipped(false);
    return false;
  }
  if (welcomeSkipped()) return false;
  // The owner went somewhere else while the list loaded.
  if (parseHash(location.hash).screen !== from) return false;
  redirect("#welcome");
  return true;
}
