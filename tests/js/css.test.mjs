// CSS lint: one token set, one font pair, and one motion system.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const FRONTEND = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "frontend");
const CSS_DIR = join(FRONTEND, "css");

const stripCss = (text) => text.replace(/\/\*[\s\S]*?\*\//g, "");
const stripHtml = (text) => text.replace(/<!--[\s\S]*?-->/g, "");

function cssFiles() {
  const files = [join(FRONTEND, "styles.css")];
  for (const name of readdirSync(CSS_DIR).sort()) {
    if (name.endsWith(".css")) files.push(join(CSS_DIR, name));
  }
  return files.map((path) => ({
    path,
    name: relative(FRONTEND, path),
    text: stripCss(readFileSync(path, "utf8")),
  }));
}

const indexHtml = () => stripHtml(readFileSync(join(FRONTEND, "index.html"), "utf8"));
const tokensCss = () => stripCss(readFileSync(join(CSS_DIR, "tokens.css"), "utf8"));

// Every "prop: value" declaration. A match that ends at "{" is a selector, not a declaration.
function declarations(css) {
  const found = [];
  const re = /(?:^|[;{}])\s*([-\w]+)\s*:([^;{}]*)(?=[;{}])/g;
  let match;
  while ((match = re.exec(css))) {
    if (css[re.lastIndex] === "{") continue;
    found.push({ prop: match[1].toLowerCase(), value: match[2].replace(/!important/i, "").trim() });
  }
  return found;
}

// Split a value on top-level commas, so cubic-bezier(a, b, c, d) stays whole.
function splitTop(value) {
  const parts = [];
  let depth = 0;
  let current = "";
  for (const ch of value) {
    if (ch === "(") depth += 1;
    if (ch === ")") depth -= 1;
    if (ch === "," && depth === 0) {
      parts.push(current.trim());
      current = "";
    } else {
      current += ch;
    }
  }
  if (current.trim()) parts.push(current.trim());
  return parts;
}

// The body of each @keyframes rule.
function keyframeBodies(css) {
  const bodies = [];
  const re = /@keyframes\s+([-\w]+)\s*\{/g;
  let match;
  while ((match = re.exec(css))) {
    let depth = 1;
    let i = re.lastIndex;
    while (i < css.length && depth > 0) {
      if (css[i] === "{") depth += 1;
      if (css[i] === "}") depth -= 1;
      i += 1;
    }
    bodies.push({ name: match[1], body: css.slice(re.lastIndex, i - 1) });
    re.lastIndex = i;
  }
  return bodies;
}

const LAYOUT = /^(width|height|min-width|max-width|min-height|max-height|top|left|right|bottom|inset|margin(-[a-z]+)?|padding(-[a-z]+)?)$/;

test("retired fonts are gone", () => {
  const retired = /Marcellus|Figtree|IBM[ +]Plex[ +]Mono/;
  for (const file of cssFiles()) assert.doesNotMatch(file.text, retired, file.name);
  const html = indexHtml();
  assert.doesNotMatch(html, retired, "index.html");
  const link = html.match(/href="(https:\/\/fonts\.googleapis\.com\/css2\?[^"]+)"/);
  assert.ok(link, "index.html loads the fonts");
  const families = new URL(link[1].replace(/&amp;/g, "&")).searchParams.getAll("family");
  assert.deepEqual(families, ["Cinzel:wght@500;600;700", "Inter:wght@400;500;600;700"]);
});

test("index.html loads the stylesheets in token order", () => {
  const sheets = [...indexHtml().matchAll(/<link rel="stylesheet" href="([^"]+)"/g)].map((m) => m[1]);
  assert.deepEqual(sheets, [
    "/css/tokens.css", "/css/base.css", "/css/shell.css", "/styles.css", "/css/forge.css", "/css/decks.css",
  ]);
});

test("accent hex values live in tokens.css only", () => {
  const accents = /#e8c26a|#9b8cff|#6fd39a|#94a8ff|#c3cdff/i;
  for (const file of cssFiles()) {
    if (file.name === join("css", "tokens.css")) continue;
    assert.doesNotMatch(file.text, accents, file.name);
  }
  assert.doesNotMatch(indexHtml(), accents, "index.html");
  // The three accents of the constraint are also banned in every script.
  const scriptAccents = /#e8c26a|#9b8cff|#6fd39a/i;
  for (const path of jsFiles(join(FRONTEND, "js"))) {
    assert.doesNotMatch(readFileSync(path, "utf8"), scriptAccents, relative(FRONTEND, path));
  }
});

test("tokens.css declares the global token set", () => {
  const values = new Map(declarations(tokensCss()).map((d) => [d.prop, d.value]));
  const exact = {
    "--gold": "#e8c26a", "--violet": "#9b8cff", "--teal": "#6fd3c7", "--success": "#6fd39a",
    "--space-1": "4px", "--space-2": "8px", "--space-3": "12px",
    "--space-4": "16px", "--space-5": "24px", "--space-6": "32px",
    "--radius-sm": "10px", "--radius-md": "14px", "--radius-lg": "22px",
    "--font-display": '"Cinzel", Georgia, serif',
    "--font-ui": '"Inter", "Segoe UI", sans-serif',
    "--font-mono": 'ui-monospace, "SF Mono", Menlo, monospace',
    "--dur-fast": "150ms", "--dur-base": "250ms", "--dur-slow": "600ms",
    "--ease-out": "cubic-bezier(0.2, 0.8, 0.2, 1)",
    "--ease-in-out": "cubic-bezier(0.65, 0, 0.35, 1)",
  };
  for (const [name, value] of Object.entries(exact)) assert.equal(values.get(name), value, name);
  const present = [
    "--bg", "--surface", "--surface-2", "--border", "--border-bright", "--text", "--text-dim",
    "--gold-bright", "--gold-dim", "--violet-dim", "--error", "--warning",
    "--mana-w", "--mana-u", "--mana-b", "--mana-r", "--mana-g", "--shadow-1", "--shadow-2",
  ];
  for (const name of present) assert.ok(values.has(name), name);
  assert.ok(!values.has("--parchment"), "--parchment became --text");
  for (const file of cssFiles()) assert.doesNotMatch(file.text, /--parchment|--(forge|decks)-[\w-]+/, file.name);
});

// Remove every var(...) and calc(...) group, nested parens included.
function stripTokenGroups(value) {
  let out = "";
  let i = 0;
  while (i < value.length) {
    const head = value.slice(i).match(/^(var|calc)\(/);
    if (!head) {
      out += value[i];
      i += 1;
      continue;
    }
    let depth = 0;
    let j = i + head[1].length;
    do {
      if (value[j] === "(") depth += 1;
      if (value[j] === ")") depth -= 1;
      j += 1;
    } while (depth > 0 && j < value.length);
    out += " ";
    i = j;
  }
  return out;
}

const RAW_TIME = /(^|[\s,])[-+]?(\d+(\.\d+)?|\.\d+)m?s(?=$|[\s,])/;
const MOTION_PROPS = new Set([
  "transition", "transition-duration", "transition-delay",
  "animation", "animation-duration", "animation-delay",
]);

// A motion value is "none", or it holds no time outside var() and calc().
function rawMotionDeclarations(text) {
  return declarations(text)
    .filter(({ prop, value }) => MOTION_PROPS.has(prop) && value !== "none")
    .filter(({ value }) => RAW_TIME.test(stripTokenGroups(value)));
}

test("the motion lint catches raw times next to tokens", () => {
  const bad = [
    ".a { transition: opacity 0.3s var(--ease-out); }",
    ".b { animation: x 2s var(--ease-out); }",
    ".c { transition: opacity var(--dur-fast) var(--ease-out), visibility 0s linear 0.8s; }",
    ".d { animation-delay: 0.18s; }",
    ".e { transition-delay: 120ms; }",
  ];
  for (const css of bad) assert.equal(rawMotionDeclarations(css).length, 1, css);
  const good = [
    ".a { transition: opacity var(--dur-fast) var(--ease-out); }",
    ".b { animation: x calc(var(--dur-slow) * 1.5) linear var(--deal-delay, 0ms) both; }",
    ".c { animation-delay: calc(var(--dur-slow) * 0.3); }",
    ".d { transition: none; }",
  ];
  for (const css of good) assert.equal(rawMotionDeclarations(css).length, 0, css);
});

// tokens.css defines the scale and the reduced-motion fallback, so it holds raw times.
test("motion declarations use tokens", () => {
  for (const file of cssFiles()) {
    if (file.name === join("css", "tokens.css")) continue;
    for (const { prop, value } of rawMotionDeclarations(file.text)) {
      assert.fail(`${file.name}: ${prop}: ${value}`);
    }
  }
});

test("transitions move only transform and opacity", () => {
  for (const file of cssFiles()) {
    for (const { prop, value } of declarations(file.text)) {
      if (prop !== "transition" && prop !== "transition-property") continue;
      for (const item of splitTop(value)) {
        const first = item.split(/\s+/)[0];
        // A shorthand item that starts with a time names no property, so it means "all".
        const name = prop === "transition" && /^(\d|\.|var\(|calc\()/.test(first) ? "all" : first;
        assert.ok(!LAYOUT.test(name) && name !== "all", `${file.name}: ${prop}: ${value}`);
      }
    }
  }
});

test("keyframes do not animate layout", () => {
  for (const file of cssFiles()) {
    for (const { name, body } of keyframeBodies(file.text)) {
      for (const { prop } of declarations(body)) {
        assert.ok(!LAYOUT.test(prop), `${file.name}: @keyframes ${name} sets ${prop}`);
      }
    }
  }
});

test("tokens.css has the reduced-motion fallback", () => {
  const css = tokensCss();
  const block = css.match(/@media\s*\(\s*prefers-reduced-motion:\s*reduce\s*\)\s*\{([\s\S]*)\}/);
  assert.ok(block, "tokens.css has a prefers-reduced-motion block");
  const props = declarations(block[1]).map((d) => d.prop);
  for (const name of ["animation-duration", "animation-iteration-count", "transition-duration"]) {
    assert.ok(props.includes(name), name);
  }
  const styles = cssFiles().find((f) => f.name === "styles.css");
  assert.doesNotMatch(styles.text, /prefers-reduced-motion/, "the global rule moved out of styles.css");
});

function jsFiles(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) out.push(...jsFiles(path));
    else if (name.endsWith(".js")) out.push(path);
  }
  return out;
}

test("only motion.js animates", () => {
  const files = jsFiles(join(FRONTEND, "js"));
  const motion = join(FRONTEND, "js", "shared", "motion.js");
  assert.ok(files.includes(motion), "motion.js exists");
  for (const path of files) {
    if (path === motion) continue;
    const text = readFileSync(path, "utf8");
    assert.ok(!text.includes(".animate("), `${relative(FRONTEND, path)} calls .animate(`);
    assert.ok(!text.includes("prefers-reduced-motion"), `${relative(FRONTEND, path)} queries reduced motion`);
  }
});
