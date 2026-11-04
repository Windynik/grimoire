// Hash router. Each screen has one view (#<screen>-view) and one module.
//
// A route change runs in this order: the old screen's leave() (awaited), then
// the view switch, then the nav mark, then the new screen's open(params).
// Route changes run one at a time, in the order they come.

export const SCREENS = ["home", "collection", "import", "forge", "decks", "settings", "welcome"];

/** A screen without its own nav link marks the link of its parent. */
export const NAV_PARENT = { import: "collection", welcome: "home" };

const DECK_HASH = /^#deck\/([A-Za-z0-9_-]+)$/;

const screens = new Map();
let shown = null; // the screen on view now
let lastHash = null; // the last hash that ran
let carried = null; // { hash, state } from navigate(), for one open() call
let queue = Promise.resolve();
let started = false;

/**
 * Map a location hash to a screen and its params.
 *
 * @param {string} hash "" or "#<screen>" or "#deck/<id>".
 * @returns {{screen: string, params: Object}} An unknown hash maps to home.
 */
export function parseHash(hash) {
  const text = String(hash || "");
  const deck = DECK_HASH.exec(text);
  if (deck) return { screen: "decks", params: { deckId: deck[1] } };
  const name = text.replace(/^#/, "");
  if (SCREENS.includes(name)) return { screen: name, params: {} };
  return { screen: "home", params: {} };
}

/**
 * Register the module of one screen.
 *
 * @param {string} screen One of SCREENS.
 * @param {{open: function(Object), leave: function(): (Promise|undefined)}} entry
 *   leave is optional. The router waits for its promise before the next screen shows.
 */
export function register(screen, entry) {
  if (!SCREENS.includes(screen)) throw new Error(`Unknown screen: ${screen}`);
  screens.set(screen, entry || {});
}

function report(error) {
  console.error("Screen error:", error);
}

function showView(screen) {
  SCREENS.forEach((name) => {
    const view = document.getElementById(`${name}-view`);
    if (view) view.classList.toggle("active", name === screen);
  });
  const navScreen = NAV_PARENT[screen] || screen;
  document.querySelectorAll(".nav-item[data-screen]").forEach((link) => {
    if (link.dataset.screen !== navScreen) {
      link.removeAttribute("aria-current");
      return;
    }
    link.setAttribute("aria-current", "page");
    // On a narrow screen the nav scrolls sideways: keep the marked link in view.
    if (typeof link.scrollIntoView === "function") {
      link.scrollIntoView({ block: "nearest", inline: "nearest" });
    }
  });
}

async function run() {
  const hash = location.hash;
  const { screen, params } = parseHash(hash);
  if (carried && carried.hash === hash) {
    params.state = carried.state;
    carried = null;
  }
  if (shown && shown !== screen) {
    const old = screens.get(shown);
    if (old && typeof old.leave === "function") {
      try {
        await old.leave();
      } catch (error) {
        // The next screen still opens. The old screen showed its own error.
        report(error);
      }
    }
  }
  shown = screen;
  showView(screen);
  // A new hash opens its view at the top, not at the old scroll position.
  if (hash !== lastHash) window.scrollTo(0, 0);
  lastHash = hash;
  const entry = screens.get(screen);
  if (!entry || typeof entry.open !== "function") return;
  // The router does not wait for open(): a slow screen must not block the nav.
  try {
    Promise.resolve(entry.open(params)).catch(report);
  } catch (error) {
    report(error);
  }
}

function dispatch() {
  queue = queue.then(run).catch(report);
  return queue;
}

/**
 * Go to a hash. When the hash does not change, the route runs again.
 *
 * @param {string} hash For example "#collection" or "#deck/abc".
 * @param {*} [state] The next open() of that hash gets it as params.state, one time.
 * @returns {Promise|undefined} The route run when the hash did not change.
 */
export function navigate(hash, state) {
  carried = state === undefined ? null : { hash, state };
  if (location.hash === hash) return dispatch();
  location.hash = hash;
  return undefined;
}

/**
 * Go to a hash in place of the current history entry. Back then skips the
 * current hash, so a screen that sends the owner away does not trap Back.
 *
 * @param {string} hash For example "#welcome".
 * @returns {Promise} The route run.
 */
export function redirect(hash) {
  carried = null;
  if (location.hash !== hash) history.replaceState(history.state, "", hash);
  return dispatch();
}

/**
 * Listen for hash changes and open the screen of the current hash.
 *
 * @returns {Promise<void>} Resolves after the first screen shows and its open() starts.
 */
export function start() {
  if (!started) {
    started = true;
    window.addEventListener("hashchange", () => dispatch());
  }
  return dispatch();
}
