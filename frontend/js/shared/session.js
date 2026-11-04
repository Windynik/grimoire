// Session values that more than one screen reads, kept in localStorage.
//
// A blocked or full storage does not stop the app: a value that the storage
// refuses stays in memory for this page session.

const ACTIVE_KEY = "lastJobId";
const SOURCE_KEY = "viewerSource";
const SKIPPED_KEY = "welcomeSkipped";

// The values that the storage refused, by key. null means "removed".
const memory = new Map();

function read(key) {
  let stored = null;
  try {
    stored = localStorage.getItem(key);
  } catch (e) {
    stored = null;
  }
  return memory.has(key) ? memory.get(key) : stored;
}

function write(key, value) {
  const empty = value === null || value === undefined || value === "";
  try {
    if (empty) localStorage.removeItem(key);
    else localStorage.setItem(key, String(value));
    memory.delete(key);
  } catch (e) {
    // The storage is blocked or full. The value stays in memory for this page.
    memory.set(key, empty ? null : String(value));
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
