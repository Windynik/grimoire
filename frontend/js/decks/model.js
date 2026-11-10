// Pure deck editor model: edit operations, undo history, grouping, save queue.
// This file never touches the DOM, so Node can import it for tests.

export const SECTIONS = ["main", "sideboard", "maybeboard"];
export const MAX_COUNT = 250; // the server accepts 1..250 copies per line

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
 * @param {Object} op One of add, inc, dec, remove, move, replace, setCommander, clearCommander.
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
  // Put the commander back in main as one copy.
  const returnCommander = () => {
    const card = next.commander;
    next.commander = null;
    const at = find("main", entryKey(card));
    if (at >= 0) {
      lines("main")[at].count = Math.min(MAX_COUNT, lines("main")[at].count + 1);
    } else {
      lines("main").push({ basic: false, role: "", reason: "", ...card, count: 1 });
    }
  };

  switch (op.type) {
    case "add": {
      const key = entryKey(op.card);
      const at = find(op.section, key);
      if (at >= 0) {
        const line = lines(op.section)[at];
        line.count = Math.min(MAX_COUNT, line.count + 1);
      } else {
        const entry = clone(op.card);
        entry.count = 1;
        lines(op.section).push(entry);
      }
      break;
    }
    case "inc": {
      const at = find(op.section, op.key);
      if (at >= 0) lines(op.section)[at].count = Math.min(MAX_COUNT, lines(op.section)[at].count + 1);
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
      let amount = Math.min(source.count, op.count > 0 ? op.count : source.count);
      const target = find(op.to, op.key);
      if (target >= 0) {
        // Move only what fits under the line limit; the rest stays in the source.
        amount = Math.min(amount, MAX_COUNT - lines(op.to)[target].count);
        if (amount <= 0) break;
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
    case "setCommander": {
      const at = find("main", op.key);
      if (at < 0) break;
      const source = lines("main")[at];
      const card = clone(source);
      delete card.count;
      source.count -= 1;
      if (source.count <= 0) lines("main").splice(at, 1);
      if (next.commander) returnCommander();
      next.commander = card;
      break;
    }
    case "clearCommander":
      if (next.commander) returnCommander();
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
 * Count the entry issues of an analysis by code.
 *
 * @param {Object} [analysisCards] Map of entry key to {issues: [code, ...]}.
 * @returns {Object} Map of issue code to the number of entries that have it.
 */
export function issueSummary(analysisCards) {
  const counts = {};
  Object.values(analysisCards || {}).forEach((info) => {
    ((info && info.issues) || []).forEach((code) => {
      counts[code] = (counts[code] || 0) + 1;
    });
  });
  return counts;
}

/** Mana value of a cost such as "{2}{W}{W}". X counts 0; a two-faced cost counts its front face. */
export function manaValue(cost) {
  const front = String(cost || "").split("//")[0];
  let total = 0;
  (front.match(/\{[^}]*\}/g) || []).forEach((symbol) => {
    const body = symbol.slice(1, -1);
    const first = body.split("/")[0];
    if (/^\d+$/.test(first)) total += Number(first);
    else if (first !== "X" && first !== "Y" && first !== "Z") total += 1;
  });
  return total;
}

/**
 * Map a search result to the card of an "add" op. Collection rows name the id
 * scryfall_id and carry a quantity; archive records may name it id. Neither
 * route returns cmc, so it comes from the mana cost.
 *
 * @param {Object} result One card of a search response.
 * @returns {Object}
 */
export function toEntryCard(result) {
  const typeLine = result.type_line || "";
  const price = Number(result.price);
  return {
    scryfall_id: result.scryfall_id || result.id || null,
    name: result.name,
    image_url: result.image_url || "",
    back_image_url: result.back_image_url || "",
    mana_cost: result.mana_cost || "",
    type_line: typeLine,
    cmc: manaValue(result.mana_cost),
    price: Number.isFinite(price) ? price : 0,
    set: result.set || "",
    basic: typeLine.includes("Basic Land"),
  };
}

/**
 * Draw cards for a sample hand. Each copy is one card, so a 4-count entry can
 * give up to 4 cards. A deck with fewer cards than size gives all of them.
 *
 * @param {Array<Object>} mainEntries Main section entries (not changed).
 * @param {function(): number} [rng] Returns a number in [0, 1).
 * @param {number} [size] Number of cards.
 * @returns {Array<Object>} One entry per card, with count 1 and a copy number.
 */
export function drawHand(mainEntries, rng = Math.random, size = 7) {
  const copies = [];
  (mainEntries || []).forEach((entry) => {
    for (let i = 0; i < entry.count; i += 1) copies.push({ ...entry, count: 1, copy: i });
  });
  // Partial Fisher-Yates: the first size places are a uniform draw.
  const take = Math.min(size, copies.length);
  for (let i = 0; i < take; i += 1) {
    const j = i + Math.floor(rng() * (copies.length - i));
    [copies[i], copies[j]] = [copies[j], copies[i]];
  }
  return copies.slice(0, take);
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

  // Start one request. The in-flight mark clears only when this request is still the current one.
  _send(snapshot, options) {
    const run = (async () => {
      try {
        await this.send(snapshot, options);
      } catch (error) {
        if (this.onError) this.onError(error);
      }
    })();
    const tracked = run.then(() => {
      if (this.inflight === tracked) this.inflight = null;
    });
    this.inflight = tracked;
    return tracked;
  }

  _take() {
    const snapshot = this.pending;
    this.hasPending = false;
    this.pending = undefined;
    return snapshot;
  }

  // Send the newest snapshot. During a request (also one that flush started), wait
  // for it, then send the snapshot that is still pending.
  _drain() {
    if (this.inflight) {
      return this.inflight.then(() => {
        if (this.hasPending && !this.timer) return this._drain();
        return undefined;
      });
    }
    if (!this.hasPending) return Promise.resolve();
    return this._send(this._take()).then(() => {
      if (this.hasPending && !this.timer) return this._drain();
      return undefined;
    });
  }

  /**
   * Send the newest snapshot now.
   *
   * Without options (the page stays open), wait for the request in flight, then
   * send only the newest snapshot, and resolve after both.
   * With {closing: true} (the page closes), send the newest snapshot at once
   * with {keepalive: true} and do not wait for a request in flight.
   */
  async flush(options) {
    clearTimeout(this.timer);
    this.timer = null;
    if (options && options.closing) {
      if (!this.hasPending) return this.inflight || undefined;
      return this._send(this._take(), { keepalive: true });
    }
    while (this.inflight) await this.inflight;
    if (this.hasPending) await this._send(this._take());
    return undefined;
  }
}

/** Return true when two states hold the same sections and commander. */
export function sameDeck(a, b) {
  return JSON.stringify([a.sections, a.commander]) === JSON.stringify([b.sections, b.commander]);
}

/** Return a copy of the sections and commander, to compare with the deck later. */
export function snapshotDeck(state) {
  return JSON.parse(JSON.stringify({ sections: state.sections, commander: state.commander }));
}

/** Return true when an agent result still fits: the deck is the one the agent read. */
export function agentResultFits(snapshot, current) {
  return sameDeck(snapshot, current);
}
