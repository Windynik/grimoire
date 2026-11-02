// Forge timeline: the five stage segments and the time left.

export const STAGE_NAMES = ["Study cards", "Find backbones", "Ask you", "Build", "Review"];

const TICK_MS = 1000;

/**
 * Format a number of seconds as "45 s", "1 min" or "1 min 15 s".
 * @param {number} seconds
 * @returns {string}
 */
export function formatSeconds(seconds) {
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) return `${total} s`;
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return rest ? `${minutes} min ${rest} s` : `${minutes} min`;
}

export class Timeline {
  /**
   * @param {HTMLElement} root List element that gets one segment per stage.
   * @param {HTMLElement} [etaEl] Element for the time left. Created in root when missing.
   */
  constructor(root, etaEl) {
    this.root = root;
    this.etaEl = etaEl || root.appendChild(document.createElement("p"));
    this.deadline = null;
    this.timer = null;
    root.textContent = "";
    this.segments = STAGE_NAMES.map((name) => {
      const item = document.createElement("li");
      item.className = "forge-seg";
      const track = document.createElement("i");
      const fill = document.createElement("b");
      track.appendChild(fill);
      const label = document.createElement("span");
      label.textContent = name;
      item.append(track, label);
      root.appendChild(item);
      return { item, fill };
    });
    this.etaEl.textContent = "";
  }

  /**
   * Show the stage at `index` as active with `progress` (0 to 1) filled.
   * Stages before it show as done. An index of 5 or more marks all stages done.
   */
  setStage(index, progress) {
    const fraction = Math.min(1, Math.max(0, Number(progress) || 0));
    this.segments.forEach(({ item, fill }, n) => {
      const done = n < index;
      const active = n === index;
      item.classList.toggle("done", done);
      item.classList.toggle("active", active);
      if (active) item.setAttribute("aria-current", "step");
      else item.removeAttribute("aria-current");
      fill.style.transform = `scaleX(${done ? 1 : active ? fraction : 0})`;
    });
  }

  /**
   * Show the time left. A number starts a countdown; null shows "Waiting for you".
   * @param {number|null} seconds
   */
  setEta(seconds) {
    this.stop();
    if (seconds === null || seconds === undefined || !Number.isFinite(Number(seconds))) {
      this.etaEl.textContent = "Waiting for you";
      return;
    }
    this.deadline = performance.now() + Number(seconds) * 1000;
    this.render();
    this.timer = setInterval(() => this.render(), TICK_MS);
  }

  /** Show "Done" and mark every stage done. */
  done() {
    this.stop();
    this.setStage(STAGE_NAMES.length, 0);
    this.etaEl.textContent = "Done";
  }

  /** Clear the time left. */
  clear() {
    this.stop();
    this.etaEl.textContent = "";
  }

  render() {
    const left = (this.deadline - performance.now()) / 1000;
    // An honest estimate: past the deadline, say so instead of counting below zero.
    this.etaEl.textContent = left >= 1 ? `About ${formatSeconds(left)} left` : "Taking longer than estimated";
  }

  stop() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    this.deadline = null;
  }

  destroy() {
    this.stop();
    this.root.textContent = "";
    this.etaEl.textContent = "";
  }
}
