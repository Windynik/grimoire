// Session values that more than one screen reads, kept in localStorage.
//
// A blocked or full storage does not stop the app: a read gives null, and a
// write does nothing.

const ACTIVE_KEY = "lastJobId";
const SOURCE_KEY = "viewerSource";
const SKIPPED_KEY = "welcomeSkipped";

function read(key) {
  try {
    return localStorage.getItem(key);
  } catch (e) {
    return null;
  }
}

function write(key, value) {
  try {
    if (value === null || value === undefined || value === "") localStorage.removeItem(key);
    else localStorage.setItem(key, String(value));
  } catch (e) {
    // The storage is blocked or full. The app continues without the value.
  }
}

/** The job id of the active collection, or null. */
export function activeCollection() {
  return read(ACTIVE_KEY);
}

/** Set the active collection. null forgets it. */
export function setActiveCollection(jobId) {
  write(ACTIVE_KEY, jobId);
}

/**
 * The source of the collection viewer: a job id, "archive" (the full archive),
 * or null (follow the active collection).
 */
export function viewerSource() {
  return read(SOURCE_KEY);
}

/** Set the source of the collection viewer. null forgets it. */
export function setViewerSource(value) {
  write(SOURCE_KEY, value);
}

/**
 * True when the owner chose "Skip — just browse all cards" on the welcome
 * screen. While there is no collection, Home and the Vault then do not send
 * the owner back to the welcome screen.
 */
export function welcomeSkipped() {
  return read(SKIPPED_KEY) === "1";
}

/** Remember (true) or forget (false) the choice to skip the welcome screen. */
export function setWelcomeSkipped(skipped) {
  write(SKIPPED_KEY, skipped ? "1" : null);
}
