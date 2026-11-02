// Pure deck editor model: edit operations, undo history, grouping, save queue.
// This file never touches the DOM, so Node can import it for tests.

export const SECTIONS = ["main", "sideboard", "maybeboard"];

const TYPE_ORDER = [
  "Creature", "Planeswalker", "Battle", "Instant", "Sorcery", "Artifact", "Enchantment", "Land",
];

/** Key that identifies a card line: its Scryfall id, or "basic:{name}". */
export function entryKey(entry) {
  return entry.scryfall_id || `basic:${entry.name}`;
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function cloneState(state) {
  return { sections: clone(state.sections), commander: clone(state.commander ?? null) };
}

/**
 * Apply one edit to a deck state. Returns a new state and never mutates the input.
 *
 * @param {{sections: Object, commander: (Object|null)}} state
 * @param {Object} op One of add, inc, dec, remove, move, replace.
 * @returns {{sections: Object, commander: (Object|null)}}
 */
export function applyOp(state, op) {
  const next = cloneState(state);
  const sections = next.sections;
  const lines = (name) => {
    if (!sections[name]) sections[name] = [];
    return sections[name];
  };
  const find = (name, key) => lines(name).findIndex((e) => entryKey(e) === key);

  switch (op.type) {
    case "add": {
      const key = entryKey(op.card);
      const at = find(op.section, key);
      if (at >= 0) {
        lines(op.section)[at].count += 1;
      } else {
        const entry = clone(op.card);
        entry.count = 1;
        lines(op.section).push(entry);
      }
      break;
    }
    case "inc": {
      const at = find(op.section, op.key);
      if (at >= 0) lines(op.section)[at].count += 1;
      break;
    }
    case "dec": {
      const at = find(op.section, op.key);
      if (at >= 0) {
        const entry = lines(op.section)[at];
        entry.count -= 1;
        if (entry.count <= 0) lines(op.section).splice(at, 1);
      }
      break;
    }
    case "remove": {
      const at = find(op.section, op.key);
      if (at >= 0) lines(op.section).splice(at, 1);
      break;
    }
    case "move": {
      const at = find(op.from, op.key);
      if (at < 0 || op.from === op.to) break;
      const source = lines(op.from)[at];
      const amount = Math.min(source.count, op.count > 0 ? op.count : source.count);
      const target = find(op.to, op.key);
      if (target >= 0) {
        lines(op.to)[target].count += amount;
      } else {
        const moved = clone(source);
        moved.count = amount;
        lines(op.to).push(moved);
      }
      source.count -= amount;
      if (source.count <= 0) lines(op.from).splice(at, 1);
      break;
    }
    case "replace":
      next.sections = clone(op.sections);
      break;
    default:
      break;
  }
  return next;
}

/** Undo and redo stack of whole deck states. Every state is a deep copy. */
export class History {
  constructor(limit = 100) {
    this.limit = limit;
    this.states = [];
    this.at = -1;
  }

  push(state) {
    this.states = this.states.slice(0, this.at + 1);
    this.states.push(cloneState(state));
    if (this.states.length > this.limit) this.states.shift();
    this.at = this.states.length - 1;
  }

  get canUndo() {
    return this.at > 0;
  }

  get canRedo() {
    return this.at >= 0 && this.at < this.states.length - 1;
  }

  undo() {
    if (!this.canUndo) return null;
    this.at -= 1;
    return cloneState(this.states[this.at]);
  }

  redo() {
    if (!this.canRedo) return null;
    this.at += 1;
    return cloneState(this.states[this.at]);
  }
}

function frontTypes(entry) {
  const front = String(entry.type_line || "").split("//")[0];
  return front.split("—")[0].split(/\s+/).filter(Boolean);
}

function typeGroup(entry) {
  const types = frontTypes(entry);
  return TYPE_ORDER.find((t) => types.includes(t)) || "Other";
}

function cmcGroup(entry) {
  if (frontTypes(entry).includes("Land")) return "Lands";
  const cmc = Math.floor(Number(entry.cmc) || 0);
  return cmc >= 7 ? "7+" : String(cmc);
}

function roleGroup(entry, analysisCards) {
  const info = analysisCards && analysisCards[entryKey(entry)];
  return entry.role || (info && info.roles && info.roles[0]) || "Other";
}

function titleRank(mode, title) {
  if (mode === "type") return TYPE_ORDER.concat(["Other"]).indexOf(title);
  if (mode === "cmc") return title === "Lands" ? -1 : title === "7+" ? 7 : Number(title);
  return title === "Other" ? 1 : 0;
}

/**
 * Group entries for display.
 *
 * @param {Object[]} entries
 * @param {"type"|"role"|"cmc"} mode
 * @param {Object} [analysisCards] Map of entry key to {roles: [...]} from the analysis.
 * @returns {{title: string, entries: Object[], count: number}[]}
 */
export function groupEntries(entries, mode, analysisCards) {
  const pick = mode === "role" ? (e) => roleGroup(e, analysisCards)
    : mode === "cmc" ? cmcGroup : typeGroup;
  const groups = new Map();
  entries.forEach((entry) => {
    const title = pick(entry);
    if (!groups.has(title)) groups.set(title, []);
    groups.get(title).push(entry);
  });
  const byCmcName = (a, b) => (Number(a.cmc) || 0) - (Number(b.cmc) || 0)
    || String(a.name).localeCompare(String(b.name));
  return [...groups.entries()]
    .map(([title, list]) => ({
      title,
      entries: list.slice().sort(byCmcName),
      count: list.reduce((sum, e) => sum + (e.count ?? 1), 0),
    }))
    .sort((a, b) => titleRank(mode, a.title) - titleRank(mode, b.title)
      || a.title.localeCompare(b.title));
}

/**
 * Debounced save queue. At most one request is in flight. A snapshot that
 * arrives during a request waits, and only the newest one goes out afterward.
 * Errors from send go to onError (if set) and do not stop the queue.
 */
export class SaveQueue {
  constructor(send, delayMs = 700) {
    this.send = send;
    this.delayMs = delayMs;
    this.onError = null;
    this.timer = null;
    this.hasPending = false;
    this.pending = undefined;
    this.inflight = null;
  }

  schedule(snapshot) {
    this.pending = snapshot;
    this.hasPending = true;
    clearTimeout(this.timer);
    this.timer = setTimeout(() => {
      this.timer = null;
      this._drain();
    }, this.delayMs);
  }

  _drain(options) {
    if (this.inflight || !this.hasPending) return this.inflight || Promise.resolve();
    const snapshot = this.pending;
    this.hasPending = false;
    this.pending = undefined;
    this.inflight = this._run(snapshot, options);
    return this.inflight;
  }

  async _run(snapshot, options) {
    try {
      await this.send(snapshot, options);
    } catch (error) {
      if (this.onError) this.onError(error);
    }
    this.inflight = null;
    if (this.hasPending && !this.timer) await this._drain();
  }

  /**
   * Send the newest snapshot now with {keepalive: true}. When a request is
   * in flight, the newest snapshot still goes out at once, because a flush
   * runs when the page closes and cannot wait.
   */
  flush() {
    clearTimeout(this.timer);
    this.timer = null;
    if (!this.hasPending) return this.inflight || Promise.resolve();
    const snapshot = this.pending;
    this.hasPending = false;
    this.pending = undefined;
    const run = this._run(snapshot, { keepalive: true });
    if (!this.inflight) this.inflight = run;
    return run;
  }
}
