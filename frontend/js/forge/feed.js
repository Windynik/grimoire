// Thinking feed: the agent's thoughts, questions, the mana curve, and the explanation.
//
// Card text and model text go into the page only as text nodes. The only
// markup this module makes is its own structure (entries, buttons, headings).

const MAX_ENTRIES = 8;
const TICK_MS = 250;
const CURVE_STAGGER_MS = 90;
export const EXPLANATION_HEADINGS = ["## Game plan", "## How to pilot", "## Key interactions", "## Weaknesses"];

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/**
 * Render explanation markdown into a container.
 *
 * The four known "## " headings become <h4>. Every other line becomes a text
 * node; blank lines split paragraphs.
 * @param {HTMLElement} container
 * @param {string} text
 */
export function renderExplanation(container, text) {
  container.textContent = "";
  let paragraph = null;
  String(text || "").split("\n").forEach((line) => {
    const trimmed = line.trim();
    if (EXPLANATION_HEADINGS.includes(trimmed)) {
      container.appendChild(el("h4", "", trimmed.slice(3)));
      paragraph = null;
      return;
    }
    if (!trimmed) {
      paragraph = null;
      return;
    }
    if (paragraph) paragraph.appendChild(document.createElement("br"));
    else paragraph = container.appendChild(el("p"));
    paragraph.appendChild(document.createTextNode(trimmed));
  });
}

/**
 * Append text to a node and put each card name it holds in <b>.
 * Longer names win over shorter names at the same position.
 */
function appendWithNames(node, text, names) {
  const wanted = new Set();
  (names || []).forEach((name) => {
    if (typeof name !== "string" || !name.trim()) return;
    wanted.add(name);
    if (name.includes(" // ")) wanted.add(name.split(" // ")[0]);
  });
  const list = [...wanted].sort((a, b) => b.length - a.length);
  let at = 0;
  while (at < text.length) {
    let found = -1;
    let match = "";
    list.forEach((name) => {
      const index = text.indexOf(name, at);
      if (index >= 0 && (found < 0 || index < found)) {
        found = index;
        match = name;
      }
    });
    if (found < 0) break;
    if (found > at) node.appendChild(document.createTextNode(text.slice(at, found)));
    node.appendChild(el("b", "", match));
    at = found + match.length;
  }
  if (at < text.length) node.appendChild(document.createTextNode(text.slice(at)));
}

export class ThoughtFeed {
  /** @param {HTMLElement} root Container for the feed. */
  constructor(root) {
    this.root = root;
    this.timers = new Set();
    this.questions = new Map();
    this.explanation = null;
    this.explanationText = "";
    this.stick = true;

    root.textContent = "";
    const head = el("h3", "forge-feed-head");
    head.append(el("span", "forge-dot"), document.createTextNode("Thinking"));
    this.list = el("div", "forge-feed-list");
    this.list.setAttribute("role", "log");
    this.list.setAttribute("aria-live", "polite");
    this.list.setAttribute("aria-label", "Agent thoughts");
    this.onScroll = () => {
      const { scrollTop, scrollHeight, clientHeight } = this.list;
      this.stick = scrollHeight - scrollTop - clientHeight < 24;
    };
    this.list.addEventListener("scroll", this.onScroll);
    root.append(head, this.list);
  }

  later(ms, fn) {
    const id = setTimeout(() => {
      this.timers.delete(id);
      fn();
    }, ms);
    this.timers.add(id);
  }

  /** Add an entry, keep the last MAX_ENTRIES (an open question stays), and scroll to it. */
  add(entry) {
    entry.classList.add("forge-entry");
    this.list.appendChild(entry);
    const removable = [...this.list.children].filter((child) => !child.classList.contains("open"));
    while (this.list.children.length > MAX_ENTRIES && removable.length) {
      const old = removable.shift();
      if (old === this.explanation) continue;
      old.remove();
    }
    requestAnimationFrame(() => entry.classList.add("show"));
    if (this.stick) this.list.scrollTop = this.list.scrollHeight;
    return entry;
  }

  /**
   * Show a thought. Names in cardNames show in bold.
   * @param {string} text
   * @param {string[]} cardNames
   */
  thought(text, cardNames) {
    const entry = el("div", "forge-thought");
    appendWithNames(entry, String(text || ""), cardNames);
    return this.add(entry);
  }

  /**
   * Show a short line of a given kind: "status", "warning" or "error".
   */
  note(text, kind) {
    return this.add(el("div", `forge-thought forge-note ${kind || "status"}`, String(text || "")));
  }

  /**
   * Show a question with one button per option and a countdown bar.
   *
   * @param {Object} q Question event: question_id, text, options [{label,
   *   description, color?}], timeout_seconds (null waits), deadline (epoch
   *   seconds, or null), default.
   * @param {function(number)} onAnswer Called with the option index. A rejected
   *   promise opens the options again while time is left.
   * @param {Object} [opts]
   * @param {number} [opts.startedAt] performance.now() when the event came in.
   *   Used only when the event has no deadline.
   */
  question(q, onAnswer, opts = {}) {
    const entry = el("div", "forge-thought forge-ask open");
    entry.appendChild(el("p", "forge-q", String(q.text || "")));
    const timer = el("div", "forge-timer");
    const timerText = el("span", "", "");
    const bar = el("i");
    timer.append(timerText, bar);
    const problem = el("p", "forge-ask-error");
    problem.hidden = true;
    const record = {
      entry, buttons: [], timerText, bar, problem, locked: false, answered: false, ticker: null,
      left: () => Infinity, timeout: 0, still: window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    };
    record.buttons = (q.options || []).map((option, index) => {
      const button = el("button", "forge-opt");
      button.type = "button";
      const swatch = el("span", `forge-sw ${option.color || ""}`);
      swatch.setAttribute("aria-hidden", "true");
      button.append(swatch, el("span", "forge-opt-label", String(option.label || `Option ${index + 1}`)));
      if (option.description) button.appendChild(el("small", "", String(option.description)));
      if (index === q.default) button.appendChild(el("span", "forge-opt-tag", "Recommended"));
      button.addEventListener("click", () => {
        if (record.locked) return;
        problem.hidden = true;
        this.lock(record, index, "Sending your choice.");
        Promise.resolve(onAnswer && onAnswer(index)).catch(() => {
          if (record.answered) return;
          problem.hidden = false;
          if (record.left() > 1) {
            problem.textContent = "Could not send your choice. Try again.";
            this.countdown(record);
          } else {
            problem.textContent = "Could not send your choice.";
          }
        });
      });
      entry.appendChild(button);
      return button;
    });
    entry.append(timer, problem);
    this.questions.set(q.question_id, record);

    const timeout = Number(q.timeout_seconds);
    if (q.timeout_seconds === null || q.timeout_seconds === undefined || !(timeout > 0)) {
      timerText.textContent = "I will wait for your answer.";
      bar.hidden = true;
    } else {
      // The server and the page share one clock, so the deadline gives the
      // real time left, also after a reload.
      const server = Number(q.deadline);
      const end = q.deadline !== null && q.deadline !== undefined && Number.isFinite(server)
        ? performance.now() + (server - Date.now() / 1000) * 1000
        : (opts.startedAt || performance.now()) + timeout * 1000;
      record.timeout = timeout;
      record.left = () => Math.max(0, (end - performance.now()) / 1000);
      if (record.left() <= 0) this.lock(record, -1, "This question is closed. Waiting for the result.");
      else this.countdown(record);
    }
    return this.add(entry);
  }

  /** Open the options and run the countdown text and bar until the time is up. */
  countdown(record) {
    record.locked = false;
    record.buttons.forEach((button) => {
      button.disabled = false;
      button.classList.remove("chosen");
    });
    if (!(record.timeout > 0)) return;
    const { bar, timerText, timeout, still } = record;
    const tick = () => {
      const seconds = Math.ceil(record.left());
      if (seconds <= 0) {
        this.lock(record, -1, "Time is up. I am taking the recommended option.");
        return;
      }
      timerText.textContent = `I will choose for you in ${seconds} s`;
      // With reduced motion the bar steps with the text instead of sliding.
      if (still) bar.style.transform = `scaleX(${record.left() / timeout})`;
    };
    bar.style.transitionDuration = "0s";
    bar.style.transform = `scaleX(${Math.min(1, record.left() / timeout)})`;
    tick();
    if (record.locked) return;
    record.ticker = setInterval(tick, TICK_MS);
    if (!still) {
      requestAnimationFrame(() => requestAnimationFrame(() => {
        if (record.locked) return;
        bar.style.transitionDuration = `${record.left()}s`;
        bar.style.transform = "scaleX(0)";
      }));
    }
  }

  lock(record, chosen, text) {
    record.locked = true;
    if (record.ticker) clearInterval(record.ticker);
    record.ticker = null;
    record.buttons.forEach((button, index) => {
      button.disabled = true;
      button.classList.toggle("chosen", index === chosen);
    });
    record.bar.style.transitionDuration = "0s";
    record.bar.style.transform = "scaleX(0)";
    if (text) record.timerText.textContent = text;
  }

  /** Mark the answer of a question: {question_id, option, by}. */
  answered(evt) {
    const record = this.questions.get(evt.question_id);
    if (!record) return;
    record.answered = true;
    record.problem.hidden = true;
    this.lock(record, evt.option, evt.by === "timeout"
      ? "No answer came, so I took the recommended option."
      : "You chose this option.");
    record.entry.classList.remove("open");
  }

  /**
   * Show the mana curve as bars that grow one after another.
   * @param {Object<string, number>} curve Cards per mana value bucket ("1" to "6+").
   */
  curve(curve) {
    const buckets = Object.keys(curve || {});
    const counts = buckets.map((b) => Number(curve[b]) || 0);
    const high = Math.max(1, ...counts);
    const peak = buckets[counts.indexOf(Math.max(...counts))];
    const entry = el("div", "forge-thought");
    entry.appendChild(document.createTextNode(peak ? `Mana curve checked. The peak is at ${peak}.` : "Mana curve checked."));
    const bars = el("div", "forge-curve");
    bars.setAttribute("role", "img");
    bars.setAttribute("aria-label", buckets.map((b, i) => `${b}: ${counts[i]}`).join(", "));
    const axis = el("div", "forge-curve-x");
    axis.setAttribute("aria-hidden", "true");
    const spans = buckets.map((b, i) => {
      const bar = el("span");
      bar.title = `${counts[i]} cards at ${b}`;
      bars.appendChild(bar);
      axis.appendChild(el("span", "", b));
      return bar;
    });
    entry.append(bars, axis);
    this.add(entry);
    spans.forEach((bar, i) => {
      this.later(120 + i * CURVE_STAGGER_MS, () => {
        bar.style.transform = `scaleY(${counts[i] / high})`;
      });
    });
    return entry;
  }

  /** Add a chunk of the explanation. The text renders through renderExplanation. */
  streamExplanation(chunk) {
    if (!this.explanation) {
      this.explanation = el("div", "forge-thought forge-explain");
      this.explanationBody = el("div", "forge-explain-body");
      this.explanation.append(el("p", "forge-explain-title", "Explanation"), this.explanationBody);
      this.add(this.explanation);
    }
    this.explanationText += String(chunk || "");
    renderExplanation(this.explanationBody, this.explanationText);
    if (this.stick) this.list.scrollTop = this.list.scrollHeight;
  }

  /** Show the deck name in display type, with an optional line under it. */
  reveal(name, detail) {
    const entry = el("div", "forge-thought forge-reveal");
    entry.appendChild(el("div", "forge-reveal-name", String(name || "")));
    if (detail) entry.appendChild(el("div", "", String(detail)));
    return this.add(entry);
  }

  destroy() {
    this.timers.forEach((id) => clearTimeout(id));
    this.timers.clear();
    this.questions.forEach((record) => record.ticker && clearInterval(record.ticker));
    this.questions.clear();
    this.list.removeEventListener("scroll", this.onScroll);
    this.root.textContent = "";
  }
}
