// DOM test harness. It boots the real frontend modules inside jsdom.
// Call loadApp once per test file: ES modules load once per process.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { JSDOM } from "jsdom";

const FRONTEND = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "frontend");

const WINDOW_GLOBALS = [
  "window", "document", "location", "history", "localStorage", "sessionStorage", "navigator",
  "Node", "Element", "HTMLElement", "HTMLDialogElement", "HTMLInputElement", "HTMLSelectElement",
  "HTMLButtonElement", "HTMLTextAreaElement", "Event", "CustomEvent", "KeyboardEvent", "MouseEvent",
  "MutationObserver", "getComputedStyle", "requestAnimationFrame", "cancelAnimationFrame",
  "DocumentFragment",
];

function setGlobal(name, value) {
  Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
}

async function parseBody(init) {
  const raw = init && init.body;
  if (typeof raw !== "string") return raw;
  try {
    return JSON.parse(raw);
  } catch (e) {
    return raw;
  }
}

function toResponse(reply) {
  const status = reply.status ?? 200;
  if ("json" in reply) {
    return new Response(JSON.stringify(reply.json), {
      status,
      headers: { "content-type": "application/json", ...(reply.headers || {}) },
    });
  }
  return new Response(reply.body ?? null, { status, headers: reply.headers || {} });
}

export async function loadApp({ hash = "", routes = {}, storage = {}, reducedMotion = false } = {}) {
  const html = readFileSync(join(FRONTEND, "index.html"), "utf8");
  const dom = new JSDOM(html, {
    url: "http://127.0.0.1:8133/" + hash,
    pretendToBeVisual: true,
  });
  const { window } = dom;

  for (const [key, value] of Object.entries(storage)) window.localStorage.setItem(key, value);

  for (const name of WINDOW_GLOBALS) {
    const value = window[name];
    setGlobal(name, typeof value === "function" && !/^[A-Z]/.test(name) ? value.bind(window) : value);
  }
  setGlobal("DragEvent", window.DragEvent || class DragEvent extends window.MouseEvent {});
  window.DragEvent = globalThis.DragEvent;

  // Stubs for browser features that jsdom lacks.
  const matchMedia = (query) => ({
    matches: /prefers-reduced-motion/.test(query) ? reducedMotion : false,
    media: query,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
  });
  window.matchMedia = matchMedia;
  setGlobal("matchMedia", matchMedia);

  const observers = [];
  class IntersectionObserver {
    constructor(callback) {
      this.callback = callback;
      this.targets = new Set();
      observers.push(this);
    }
    observe(el) { this.targets.add(el); }
    unobserve(el) { this.targets.delete(el); }
    disconnect() { this.targets.clear(); }
  }
  window.IntersectionObserver = IntersectionObserver;
  setGlobal("IntersectionObserver", IntersectionObserver);
  window.__intersect = () => {
    for (const obs of observers) {
      const entries = [...obs.targets].map((target) => ({
        target, isIntersecting: true, intersectionRatio: 1,
      }));
      if (entries.length) obs.callback(entries, obs);
    }
  };

  window.Element.prototype.animate = function animate() {
    return { finished: Promise.resolve(), cancel() {}, onfinish: null };
  };
  const dialog = window.HTMLDialogElement.prototype;
  if (!dialog.showModal) {
    dialog.showModal = function showModal() { this.setAttribute("open", ""); };
  }
  if (!dialog.close) {
    dialog.close = function close() {
      this.removeAttribute("open");
      this.dispatchEvent(new window.Event("close"));
    };
  }
  window.Element.prototype.scrollIntoView = function scrollIntoView() {};
  // jsdom prints "Not implemented" for scrollTo. A test can put its own spy here.
  window.scrollTo = function scrollTo() {};
  setGlobal("scrollTo", window.scrollTo);
  URL.createObjectURL = () => "blob:grimoire-test";
  URL.revokeObjectURL = () => {};
  const clipboard = { writes: [], async writeText(text) { this.writes.push(text); } };
  Object.defineProperty(window.navigator, "clipboard", { value: clipboard, configurable: true });

  // The route stub for fetch.
  const table = { ...routes };
  const fetchLog = [];
  const stubFetch = async (input, init = {}) => {
    const url = new URL(typeof input === "string" ? input : input.url, "http://127.0.0.1:8133/");
    const method = (init.method || (typeof input === "object" && input.method) || "GET").toUpperCase();
    const req = { method, path: url.pathname, query: url.searchParams, body: await parseBody(init) };
    fetchLog.push(req);
    const key = `${method} ${url.pathname}`;
    const handler = table[key];
    if (!handler) return toResponse({ status: 404, json: { detail: `no stub for ${key}` } });
    return toResponse(await handler(req));
  };
  setGlobal("fetch", stubFetch);
  window.fetch = stubFetch;

  if (window.document.readyState !== "complete") {
    await new Promise((resolve) => window.addEventListener("load", resolve, { once: true }));
  }

  const scripts = [...window.document.querySelectorAll('script[type="module"][src]')];
  for (const script of scripts) {
    const src = script.getAttribute("src").replace(/^\//, "");
    await import(pathToFileURL(join(FRONTEND, src)).href);
  }

  const app = {
    window,
    document: window.document,
    fetchLog,
    route(key, handler) { table[key] = handler; },
    async until(predicate, timeoutMs = 2000) {
      const start = Date.now();
      while (Date.now() - start < timeoutMs) {
        const value = await predicate();
        if (value) return value;
        await new Promise((resolve) => setTimeout(resolve, 10));
      }
      throw new Error(`until timed out after ${timeoutMs} ms: ${predicate.toString()}`);
    },
    async settle() {
      for (let i = 0; i < 3; i++) await new Promise((resolve) => setTimeout(resolve, 0));
    },
  };
  await app.until(() => window.document.documentElement.dataset.ready === "true");
  await app.settle();
  return app;
}
