// Forge stage: the center card, the orbit, the synergy web, and the progress ring.
//
// One requestAnimationFrame loop moves the cards and the lines. The loop stops
// while the stage is not on screen (hidden tab, other view) and in destroy().
// With reduced motion the cards sit in a static grid and every change shows at once.

import { cardImage, cardImg } from "../shared/images.js";
import { onReducedMotionChange, reducedMotion } from "../shared/motion.js";

const SVG_NS = "http://www.w3.org/2000/svg";
const MAX_CARDS = 24; // card elements on the stage at most
const CARD_W = 62;
const CARD_H = 86;
const CENTER_Y = 0.47; // center height as a share of the stage height
const RING_LENGTH = 578; // circumference of the ring circle (r = 92)
const ORBIT_SPEED = 0.21; // radians per second
const SLOW_SPEED = 0.06;
const INNER_FACTOR = 1.4; // the inner orbit turns faster
const INNER_RADIUS = 0.62;
const EASE = 0.06; // share of the gap a card closes per 60 Hz frame
const LINE_MS = 700;
const LINE_STAGGER_MS = 200;
const LINE_SPREAD_MS = 1500; // all lines start inside this time
const MAX_LINES = 48;
const MAX_LINES_NARROW = 20; // a narrow stage draws fewer lines over the center
const FADE_MS = 800;
const NARROW = 560; // below this width, clusters sit above and below the center
const TOP_BAR = 52;
const BOTTOM_BAR = 58;
const COLORS = ["gold", "violet", "teal"];

function el(tag, className) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  return node;
}

// The id of a stage card is its Scryfall id; cardImg reads scryfall_id.
function imageCard(card) {
  return { ...card, scryfall_id: card.scryfall_id || card.id };
}

// Put the image of card into holder, unless holder shows that image already.
// Returns false when the card has no image.
function showArt(holder, card, options) {
  const art = imageCard(card);
  const src = cardImage(art);
  if (src && holder.dataset.src !== src) holder.replaceChildren(cardImg(art, options));
  if (!src) holder.replaceChildren();
  holder.dataset.src = src;
  holder.hidden = !src;
  return Boolean(src);
}

function svg(tag, attrs) {
  const node = document.createElementNS(SVG_NS, tag);
  Object.entries(attrs || {}).forEach(([key, value]) => node.setAttribute(key, value));
  return node;
}

function easeOut(t) {
  return 1 - Math.pow(1 - t, 3);
}

/** Return a function that places item i of n items in a grid that fits the box. */
function gridIn(box, n) {
  let best = { cols: 1, rows: n, scale: 0 };
  for (let cols = 1; cols <= Math.max(1, n); cols++) {
    const rows = Math.ceil(n / cols);
    const scale = Math.min(1, box.w / (cols * (CARD_W + 10)), box.h / (rows * (CARD_H + 12)));
    if (scale > best.scale) best = { cols, rows, scale };
  }
  const cellW = (CARD_W + 10) * best.scale;
  const cellH = (CARD_H + 12) * best.scale;
  const left = box.x + (box.w - Math.min(n, best.cols) * cellW) / 2 + cellW / 2;
  const top = box.y + (box.h - best.rows * cellH) / 2 + cellH / 2;
  return (i) => ({
    x: left + (i % best.cols) * cellW,
    y: top + Math.floor(i / best.cols) * cellH,
    scale: Math.max(0.3, best.scale),
  });
}

export class ForgeStage {
  /** @param {HTMLElement} root The stage area. The stage adds one layer to it. */
  constructor(root) {
    this.root = root;
    this.bodies = new Map(); // card id -> body
    this.catalog = new Map(); // card id -> card fields
    this.reasons = new Map(); // card id -> latest reason text
    this.clusters = [];
    this.lines = [];
    this.halos = [];
    this.timers = new Set();
    this.centerId = null;
    this.chosen = undefined;
    this.phase = 0;
    this.speed = ORBIT_SPEED;
    this.progress = 0;
    this.ringShown = -1;
    this.raf = null;
    this.last = 0;
    this.width = root.clientWidth || 800;
    this.height = root.clientHeight || 600;
    this.onScreen = true;
    this.tipFor = null;
    this.destroyed = false;
    this.reduced = reducedMotion();

    this.build();
    this.frame = this.frame.bind(this);
    this.onVisibility = () => this.kick();
    this.onKey = (event) => {
      if (event.key === "Escape") this.hideTip();
    };
    this.offMotion = onReducedMotionChange((reduced) => {
      this.reduced = reduced;
      this.relayout();
    });
    document.addEventListener("visibilitychange", this.onVisibility);
    root.addEventListener("keydown", this.onKey);
    this.resizer = new ResizeObserver(() => {
      this.width = root.clientWidth;
      this.height = root.clientHeight;
      this.relayout();
    });
    this.resizer.observe(root);
    this.watcher = new IntersectionObserver((entries) => {
      this.onScreen = entries[entries.length - 1].isIntersecting;
      this.kick();
    });
    this.watcher.observe(root);
    this.kick();
  }

  // -------------------------------------------------------------------------
  // DOM
  // -------------------------------------------------------------------------

  build() {
    const layer = el("div", "forge-layer");
    this.layer = layer;
    this.linksSvg = svg("svg", { class: "forge-links", "aria-hidden": "true" });
    this.haloLayer = el("div", "forge-halos");
    this.haloLayer.setAttribute("aria-hidden", "true");

    this.ring = svg("svg", { class: "forge-ring", viewBox: "0 0 200 200", "aria-hidden": "true" });
    const defs = svg("defs");
    const gradient = svg("linearGradient", { id: "forge-ring-gradient" });
    // The stop colors come from the tokens in css/tokens.css.
    gradient.append(svg("stop", { offset: "0", style: "stop-color: var(--violet)" }),
      svg("stop", { offset: "1", style: "stop-color: var(--gold)" }));
    defs.appendChild(gradient);
    this.ringFill = svg("circle", {
      class: "forge-ring-fill", cx: "100", cy: "100", r: "92",
      stroke: "url(#forge-ring-gradient)", "stroke-dasharray": String(RING_LENGTH),
      "stroke-dashoffset": String(RING_LENGTH),
    });
    this.ring.append(defs, svg("circle", { class: "forge-ring-track", cx: "100", cy: "100", r: "92" }),
      this.ringFill);

    this.core = el("button", "forge-core");
    this.core.type = "button";
    this.core.setAttribute("aria-label", "Deck center");
    this.coreArt = el("span", "forge-core-art");
    this.coreArt.hidden = true;
    this.corePlaceholder = el("span", "forge-core-sigil");
    this.corePlaceholder.textContent = "G";
    this.core.append(this.coreArt, this.corePlaceholder);
    this.bindTip(this.core, () => this.centerId);

    const meta = el("div", "forge-core-meta");
    this.pctEl = el("div", "forge-pct");
    this.pctEl.textContent = "0%";
    this.countEl = el("div", "forge-count");
    meta.append(this.pctEl, this.countEl);

    this.cardLayer = el("div", "forge-cards");

    this.tip = el("div", "forge-tip");
    this.tip.id = "forge-tip";
    this.tip.setAttribute("role", "tooltip");
    this.tip.hidden = true;
    this.tipArt = el("span", "forge-tip-art");
    this.tipArt.hidden = true;
    this.tipName = el("strong");
    this.tipType = el("small");
    this.tipReason = el("p");
    this.tip.append(this.tipArt, this.tipName, this.tipType, this.tipReason);

    layer.append(this.linksSvg, this.haloLayer, this.ring, this.cardLayer, this.core, meta, this.tip);
    this.root.prepend(layer);
  }

  later(ms, fn) {
    const id = setTimeout(() => {
      this.timers.delete(id);
      if (!this.destroyed) fn();
    }, ms);
    this.timers.add(id);
  }

  makeBody(card, mode) {
    const button = el("button", "forge-card");
    button.type = "button";
    button.setAttribute("aria-label", card.name || "Card");
    const art = imageCard(card);
    if (cardImage(art)) button.append(cardImg(art));
    else button.classList.add("forge-card-text");
    const label = el("span", "forge-card-label");
    label.textContent = card.name || "";
    button.append(label);
    this.cardLayer.appendChild(button);
    const angle = Math.random() * Math.PI * 2;
    const far = Math.max(this.width, this.height) * 0.75;
    const body = {
      id: card.id, card, el: button, mode, slot: 0, r: 1, fx: 0, fy: 0, fscale: 1,
      x: this.width / 2 + Math.cos(angle) * far, y: this.height * CENTER_Y + Math.sin(angle) * far,
      clusters: [], primary: null, dim: false, z: 0,
    };
    this.bindTip(button, () => body.id);
    this.bodies.set(card.id, body);
    return body;
  }

  removeBody(body, fade) {
    this.bodies.delete(body.id);
    if (this.tipFor === body.id) this.hideTip();
    if (!fade || this.reduced) {
      body.el.remove();
      return;
    }
    this.setDim(body, true);
    this.later(FADE_MS, () => body.el.remove());
  }

  setDim(body, dim) {
    body.dim = dim;
    body.el.classList.toggle("dim", dim);
    body.el.tabIndex = dim ? -1 : 0;
    if (dim) body.el.setAttribute("aria-hidden", "true");
    else body.el.removeAttribute("aria-hidden");
    if (dim && this.tipFor === body.id) this.hideTip();
  }

  visibleBodies() {
    return [...this.bodies.values()].filter((b) => !b.dim);
  }

  // -------------------------------------------------------------------------
  // Tooltip
  // -------------------------------------------------------------------------

  bindTip(element, idOf) {
    const show = () => this.showTip(idOf());
    const hide = () => this.hideTip();
    element.addEventListener("pointerenter", show);
    element.addEventListener("focus", show);
    element.addEventListener("pointerleave", hide);
    element.addEventListener("blur", hide);
    element.addEventListener("click", show); // touch screens have no hover
  }

  showTip(id) {
    const card = id && this.catalog.get(id);
    if (!card) return;
    this.tipFor = id;
    showArt(this.tipArt, card, { priority: "high" });
    this.tipName.textContent = card.name || "";
    this.tipType.textContent = card.type_line || "";
    this.tipReason.textContent = this.reasons.get(id) || "No reason for this card yet.";
    this.tip.hidden = false;
    const owner = id === this.centerId ? this.core : this.bodies.get(id)?.el;
    if (owner) owner.setAttribute("aria-describedby", "forge-tip");
    this.placeTip();
    this.kick();
  }

  hideTip() {
    if (!this.tipFor) return;
    const owner = this.tipFor === this.centerId ? this.core : this.bodies.get(this.tipFor)?.el;
    if (owner) owner.removeAttribute("aria-describedby");
    this.tipFor = null;
    this.tip.hidden = true;
  }

  placeTip() {
    if (!this.tipFor) return;
    const body = this.bodies.get(this.tipFor);
    const x = body ? body.x : this.width / 2;
    const y = body ? body.y : this.height * CENTER_Y;
    const w = this.tip.offsetWidth || 200;
    const h = this.tip.offsetHeight || 300;
    const gap = body ? 40 : 70;
    let left = x + gap;
    if (left + w > this.width - 8) left = x - gap - w;
    left = Math.min(Math.max(8, left), Math.max(8, this.width - w - 8));
    const top = Math.min(Math.max(8, y - h / 2), Math.max(8, this.height - h - 8));
    this.tip.style.transform = `translate(${Math.round(left)}px, ${Math.round(top)}px)`;
  }

  // -------------------------------------------------------------------------
  // Public API
  // -------------------------------------------------------------------------

  /** Remember card fields (for tooltips and later placement) without drawing them. */
  remember(cards) {
    (cards || []).forEach((card) => {
      if (card && card.id) this.catalog.set(card.id, card);
    });
  }

  /** Put a card in the center, or the placeholder sigil for null. */
  setCenter(card) {
    if (this.tipFor && this.tipFor === this.centerId) this.hideTip();
    if (!card || !card.id) {
      this.centerId = null;
      showArt(this.coreArt, {});
      this.corePlaceholder.hidden = false;
      this.core.setAttribute("aria-label", "Deck center");
      return;
    }
    this.catalog.set(card.id, card);
    this.centerId = card.id;
    const body = this.bodies.get(card.id);
    if (body) this.removeBody(body, false);
    this.corePlaceholder.hidden = showArt(this.coreArt, card, { priority: "high" });
    this.core.setAttribute("aria-label", card.name || "Deck center");
    this.relayout();
  }

  /** Orbit these cards around the center. Cards not in the list leave. */
  setCards(cards) {
    const list = (cards || []).filter((c) => c && c.id && c.id !== this.centerId);
    this.remember(list);
    const keep = new Set(list.slice(0, MAX_CARDS).map((c) => c.id));
    this.bodies.forEach((body) => {
      if (!keep.has(body.id) && body.mode !== "inner") this.removeBody(body, true);
    });
    list.slice(0, MAX_CARDS).forEach((card) => {
      const body = this.bodies.get(card.id) || this.makeBody(card, "orbit");
      if (body.dim) this.setDim(body, false);
      if (body.mode !== "inner") body.mode = "orbit";
    });
    this.reslot();
    this.relayout();
  }

  /** Flash a card violet, as the agent reads it. */
  flashRead(cardId) {
    const body = this.bodies.get(cardId);
    if (!body || body.dim) return;
    body.el.classList.add("read");
    this.later(600, () => body.el.classList.remove("read"));
  }

  /**
   * Open the orbit into clusters with halos, and draw lines between linked cards.
   * @param {Array} clusters [{backbone_id, name, size, members, color}]
   * @param {Array} edges [{src, dst, hook, label}]
   */
  showGraph(clusters, edges) {
    this.clearLines(false);
    this.clusters = (clusters || []).slice(0, COLORS.length).map((c, i) => ({
      id: c.backbone_id,
      name: String(c.name || ""),
      size: Number(c.size) || (c.members || []).length,
      members: new Set(c.members || []),
      color: COLORS.includes(c.color) ? c.color : COLORS[i],
    }));
    this.bodies.forEach((body) => {
      body.clusters = this.clusters.filter((c) => c.members.has(body.id));
      body.primary = body.clusters[0] || null;
      if (body.primary) {
        body.mode = "fixed";
        if (body.dim) this.setDim(body, false);
      } else if (body.mode !== "inner") {
        this.setDim(body, true);
      }
    });
    this.speed = SLOW_SPEED;
    this.relayout();
    this.buildHalos();

    const ok = (id) => id === this.centerId || (this.bodies.has(id) && !this.bodies.get(id).dim);
    const seen = new Set();
    const picked = [];
    (edges || []).forEach((edge) => {
      if (!edge || edge.src === edge.dst || !ok(edge.src) || !ok(edge.dst)) return;
      const key = [edge.src, edge.dst].sort().join("|");
      if (seen.has(key)) return;
      seen.add(key);
      const shared = this.clusters.find((c) => this.inCluster(c, edge.src) && this.inCluster(c, edge.dst));
      picked.push({ edge, shared });
    });
    picked.sort((a, b) => (a.shared ? 0 : 1) - (b.shared ? 0 : 1));
    const chosen = picked.slice(0, this.width < NARROW ? MAX_LINES_NARROW : MAX_LINES);
    const step = Math.min(LINE_STAGGER_MS, LINE_SPREAD_MS / Math.max(1, chosen.length));
    const start = performance.now() + 500;
    chosen.forEach(({ edge, shared }, i) => {
      const color = shared ? shared.color : (this.bodies.get(edge.src)?.primary?.color || "gold");
      const line = svg("line", { class: `${color}${shared ? "" : " cross"}` });
      this.linksSvg.appendChild(line);
      this.lines.push({ src: edge.src, dst: edge.dst, el: line, start: start + i * step, cluster: shared || null });
    });
    this.kick();
  }

  inCluster(cluster, id) {
    return cluster.members.has(id) || id === this.centerId;
  }

  buildHalos() {
    this.halos.forEach((h) => h.el.remove());
    this.halos = [];
    const groups = this.groups();
    groups.forEach((group, g) => {
      group.boxes.forEach((box, b) => {
        const halo = el("div", `forge-halo ${group.cluster.color}`);
        if (b === 0) {
          const label = el("span", "forge-halo-label");
          label.textContent = `${group.cluster.name} · ${group.cluster.size} cards`;
          halo.appendChild(label);
        }
        this.haloLayer.appendChild(halo);
        this.halos.push({ cluster: group.cluster, el: halo, bodies: box.bodies });
        this.later(this.reduced ? 0 : 300 + g * 250, () => halo.classList.add("show"));
      });
    });
    this.placeHalos();
  }

  placeHalos() {
    this.halos.forEach((halo) => {
      if (!halo.bodies.length) return;
      const pad = 18;
      const xs = halo.bodies.map((b) => b.fx);
      const ys = halo.bodies.map((b) => b.fy);
      const s = halo.bodies[0].fscale;
      const left = Math.max(4, Math.min(...xs) - (CARD_W / 2) * s - pad);
      const right = Math.min(this.width - 4, Math.max(...xs) + (CARD_W / 2) * s + pad);
      const top = Math.max(TOP_BAR - 12, Math.min(...ys) - (CARD_H / 2) * s - pad);
      const bottom = Math.min(this.height - BOTTOM_BAR + 8, Math.max(...ys) + (CARD_H / 2) * s + pad);
      Object.assign(halo.el.style, {
        left: `${left}px`, top: `${top}px`, width: `${right - left}px`, height: `${bottom - top}px`,
      });
    });
  }

  /** Pulse the halos of these backbones. An empty list stops the pulse. */
  pulse(backboneIds) {
    const ids = new Set(backboneIds || []);
    this.halos.forEach((h) => h.el.classList.toggle("pulse", ids.has(h.cluster.id)));
  }

  /**
   * Keep one backbone: the others fade, and its cards move to the inner orbit.
   * @param {string|null} backboneId Null keeps every card on the stage.
   */
  choose(backboneId) {
    if (this.chosen !== undefined) return;
    this.chosen = backboneId;
    const cluster = this.clusters.find((c) => c.id === backboneId) || null;
    this.pulse([]);
    this.halos.forEach((h) => {
      if (h.cluster !== cluster) h.el.classList.remove("show");
    });
    const keep = (body) => !cluster || body.clusters.includes(cluster) || body.mode === "inner";
    this.bodies.forEach((body) => {
      if (!keep(body)) this.setDim(body, true);
    });
    this.lines.forEach((line) => {
      if (!cluster || line.cluster !== cluster) line.el.classList.add("off");
    });
    this.later(this.reduced ? 0 : 650, () => {
      this.halos.forEach((h) => h.el.classList.remove("show"));
      this.clearLines(true);
      this.bodies.forEach((body) => {
        if (body.dim) return;
        body.mode = "inner";
        body.el.classList.add("forge-glow");
      });
      this.speed = ORBIT_SPEED;
      this.reslot();
      this.relayout();
    });
    this.relayout();
  }

  /**
   * Pull placed cards into the inner orbit and update the counter.
   * Only MAX_CARDS cards are drawn; the counter counts every card.
   */
  place(cardIds, count, size) {
    (cardIds || []).forEach((id) => {
      if (id === this.centerId) return;
      let body = this.bodies.get(id);
      if (!body) {
        const card = this.catalog.get(id);
        if (!card || this.visibleBodies().length >= MAX_CARDS) return;
        body = this.makeBody(card, "inner");
      }
      if (body.dim) this.setDim(body, false);
      body.mode = "inner";
      body.el.classList.add("forge-glow");
    });
    if (Number.isFinite(Number(count)) && Number(size) > 0) {
      this.countEl.textContent = `${count} / ${size} cards`;
    }
    this.reslot();
    this.relayout();
  }

  /** Set the ring and the percentage (fraction from 0 to 1). */
  setProgress(fraction) {
    this.progress = Math.min(1, Math.max(0, Number(fraction) || 0));
    this.pctEl.textContent = `${Math.round(this.progress * 100)}%`;
    this.kick();
  }

  /** Set the reason the tooltip shows for a card. */
  setReason(cardId, text) {
    if (!cardId || !text) return;
    this.reasons.set(cardId, String(text));
    if (this.tipFor === cardId) this.tipReason.textContent = String(text);
  }

  destroy() {
    this.destroyed = true;
    if (this.raf) cancelAnimationFrame(this.raf);
    this.raf = null;
    this.timers.forEach((id) => clearTimeout(id));
    this.timers.clear();
    this.resizer.disconnect();
    this.watcher.disconnect();
    this.offMotion();
    document.removeEventListener("visibilitychange", this.onVisibility);
    this.root.removeEventListener("keydown", this.onKey);
    this.layer.remove();
    this.bodies.clear();
  }

  // -------------------------------------------------------------------------
  // Layout
  // -------------------------------------------------------------------------

  clearLines(fade) {
    const old = this.lines;
    this.lines = [];
    old.forEach((line) => {
      if (!fade || this.reduced) {
        line.el.remove();
        return;
      }
      line.el.classList.add("off");
      this.later(FADE_MS, () => line.el.remove());
    });
  }

  reslot() {
    ["orbit", "inner"].forEach((mode) => {
      const list = [...this.bodies.values()].filter((b) => b.mode === mode && !b.dim);
      list.forEach((body, i) => {
        body.slot = i / Math.max(1, list.length);
        body.r = 0.92 + (i % 3) * 0.06;
      });
    });
  }

  /** Return the free boxes around the center: [a, b, c] (c holds a third cluster). */
  boxes() {
    const W = this.width;
    const H = this.height;
    const cx = W / 2;
    const cy = H * CENTER_Y;
    // The ring is 1.72 times the center card width (see forge.css).
    const half = ((this.core.offsetWidth || 116) * 1.72) / 2;
    const bottom = H - BOTTOM_BAR;
    const below = cy + half + 60; // under the percentage and the card counter
    if (W < NARROW) {
      const above = { x: 10, y: TOP_BAR, w: W - 20, h: Math.max(40, cy - half - TOP_BAR - 4) };
      const under = { x: 10, y: below, w: W - 20, h: Math.max(40, bottom - below) };
      const halfW = (W - 30) / 2;
      return {
        two: [above, under],
        three: [above, { x: 10, y: below, w: halfW, h: under.h }, { x: 20 + halfW, y: below, w: halfW, h: under.h }],
      };
    }
    const sideW = cx - half - 24;
    const left = { x: 12, y: TOP_BAR, w: sideW, h: bottom - TOP_BAR };
    const right = { x: cx + half + 12, y: TOP_BAR, w: sideW, h: bottom - TOP_BAR };
    const under = { x: cx - half - 6, y: below, w: 2 * half + 12, h: Math.max(40, bottom - below) };
    return { two: [left, right], three: [left, right, under] };
  }

  /** Group the fixed cards by their primary cluster and give each group its boxes. */
  groups() {
    const fixed = [...this.bodies.values()].filter((b) => b.mode === "fixed" && !b.dim && b.primary);
    const groups = this.clusters
      .map((cluster) => ({ cluster, bodies: fixed.filter((b) => b.primary === cluster), boxes: [] }))
      .filter((g) => g.bodies.length);
    const boxes = this.boxes();
    if (groups.length === 1) {
      const [a, b] = boxes.two;
      const bodies = groups[0].bodies;
      const split = Math.ceil(bodies.length / 2);
      groups[0].boxes = [{ box: a, bodies: bodies.slice(0, split) }, { box: b, bodies: bodies.slice(split) }]
        .filter((part) => part.bodies.length);
    } else {
      const list = groups.length === 2 ? boxes.two : boxes.three;
      groups.forEach((group, i) => {
        group.boxes = [{ box: list[i], bodies: group.bodies }];
      });
    }
    return groups;
  }

  /** Compute the fixed positions (clusters, and every card with reduced motion). */
  relayout() {
    // A hidden stage has no size; the resize observer lays it out once it shows.
    if (this.destroyed || !this.width || !this.height) return;
    this.groups().forEach((group) => {
      group.boxes.forEach(({ box, bodies }) => {
        const at = gridIn(box, bodies.length);
        bodies.forEach((body, i) => {
          const spot = at(i);
          body.fx = spot.x;
          body.fy = spot.y;
          body.fscale = spot.scale;
        });
      });
    });
    if (this.reduced) {
      const moving = [...this.bodies.values()].filter((b) => b.mode !== "fixed" && !b.dim);
      const [a, b] = this.boxes().two;
      const split = Math.ceil(moving.length / 2);
      [[a, moving.slice(0, split)], [b, moving.slice(split)]].forEach(([box, list]) => {
        const at = gridIn(box, list.length);
        list.forEach((body, i) => {
          const spot = at(i);
          body.fx = spot.x;
          body.fy = spot.y;
          body.fscale = spot.scale;
        });
      });
    }
    this.placeHalos();
    this.kick();
  }

  // -------------------------------------------------------------------------
  // Animation loop
  // -------------------------------------------------------------------------

  /** Start the loop when it is not running and the stage is on screen. */
  kick() {
    if (this.destroyed || !this.isShown()) return;
    if (this.reduced) {
      // Nothing moves: draw the new state now, once.
      if (this.raf) cancelAnimationFrame(this.raf);
      this.frame(performance.now());
      return;
    }
    if (this.raf) return;
    this.last = 0;
    this.raf = requestAnimationFrame(this.frame);
  }

  isShown() {
    return !document.hidden && this.onScreen;
  }

  point(id) {
    if (id === this.centerId) return { x: this.width / 2, y: this.height * CENTER_Y };
    const body = this.bodies.get(id);
    return body && !body.dim ? body : null;
  }

  frame(now) {
    this.raf = null;
    if (this.destroyed || !this.isShown()) return;
    const still = this.reduced;
    const dt = this.last ? Math.min(0.05, (now - this.last) / 1000) : 1 / 60;
    this.last = now;
    if (!still) this.phase += dt * this.speed;
    const W = this.width;
    const H = this.height;
    const cx = W / 2;
    const cy = H * CENTER_Y;
    const radius = Math.min(W * 0.42, 330);
    const narrow = W < NARROW ? 0.72 : 1;
    const k = still ? 1 : 1 - Math.pow(1 - EASE, dt * 60);
    let moving = false;

    this.bodies.forEach((body) => {
      let tx = body.fx;
      let ty = body.fy;
      let scale = body.fscale;
      let tilt = 0;
      let z = 3;
      if (!still && body.mode !== "fixed") {
        const inner = body.mode === "inner";
        const angle = this.phase * (inner ? INNER_FACTOR : 1) + body.slot * Math.PI * 2;
        const r = (inner ? INNER_RADIUS : body.r) * radius;
        tx = cx + Math.cos(angle) * r;
        ty = cy + Math.sin(angle) * r * 0.55;
        scale = (0.85 + Math.sin(angle) * 0.15) * narrow * (inner ? 0.86 : 1);
        tilt = Math.cos(angle) * 5;
        z = Math.sin(angle) < 0 ? 1 : 3;
      }
      const dx = tx - body.x;
      const dy = ty - body.y;
      body.x += dx * k;
      body.y += dy * k;
      if (Math.abs(dx) + Math.abs(dy) > 0.5) moving = true;
      body.el.style.transform = `translate(${(body.x - CARD_W / 2).toFixed(1)}px, ${(body.y - CARD_H / 2).toFixed(1)}px) scale(${scale.toFixed(3)}) rotate(${tilt.toFixed(2)}deg)`;
      if (z !== body.z) {
        body.z = z;
        body.el.style.zIndex = String(z);
      }
    });

    this.lines.forEach((line) => {
      const a = this.point(line.src);
      const b = this.point(line.dst);
      if (!a || !b) {
        line.el.setAttribute("visibility", "hidden");
        return;
      }
      line.el.removeAttribute("visibility");
      const t = still ? 1 : easeOut(Math.min(1, Math.max(0, (now - line.start) / LINE_MS)));
      if (t < 1) moving = true;
      line.el.setAttribute("x1", a.x.toFixed(1));
      line.el.setAttribute("y1", a.y.toFixed(1));
      line.el.setAttribute("x2", (a.x + (b.x - a.x) * t).toFixed(1));
      line.el.setAttribute("y2", (a.y + (b.y - a.y) * t).toFixed(1));
      line.el.style.opacity = t > 0 ? "" : "0";
    });

    const target = this.progress;
    if (this.ringShown < 0 || still) this.ringShown = target;
    else this.ringShown += (target - this.ringShown) * Math.min(1, dt * 4);
    if (Math.abs(target - this.ringShown) > 0.001) moving = true;
    this.ringFill.setAttribute("stroke-dashoffset", (RING_LENGTH * (1 - this.ringShown)).toFixed(1));

    if (this.tipFor) this.placeTip();
    const orbiting = [...this.bodies.values()].some((b) => b.mode !== "fixed" && !b.dim);
    if (!still && (moving || orbiting)) this.raf = requestAnimationFrame(this.frame);
  }
}
