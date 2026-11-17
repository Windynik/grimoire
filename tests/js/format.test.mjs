// One date format for the whole app (frontend/js/shared/format.js).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { formatDate, formatDay } from "../../frontend/js/shared/format.js";

const JS = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "frontend", "js");

test("formatDay gives day, short month and year", () => {
  assert.equal(formatDay("2026-11-14T12:20:39"), "14 Nov 2026");
  assert.equal(formatDay("2026-07-04T00:30:00"), "4 Jul 2026");
});

test("formatDay gives an empty text for no date or a bad date", () => {
  assert.equal(formatDay(null), "");
  assert.equal(formatDay(""), "");
  assert.equal(formatDay(undefined), "");
  assert.equal(formatDay("not a date"), "");
});

test("formatDate adds the time in 24-hour form", () => {
  assert.equal(formatDate("2026-11-14T12:20:39"), "14 Nov 2026, 12:20");
  assert.equal(formatDate("2026-11-14T09:05:00"), "14 Nov 2026, 09:05");
});

test("formatDate gives a dash for no date or a bad date", () => {
  assert.equal(formatDate(null), "—");
  assert.equal(formatDate("not a date"), "—");
});

function jsFiles(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return jsFiles(path);
    return name.endsWith(".js") ? [path] : [];
  });
}

test("only shared/format.js formats a date", () => {
  const own = join(JS, "shared", "format.js");
  for (const path of jsFiles(JS)) {
    if (path === own) continue;
    assert.doesNotMatch(readFileSync(path, "utf8"), /toLocaleDateString/, relative(JS, path));
  }
});
