import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

import {
  DARK_MEDIA_QUERY,
  THEME_CHOICES,
  THEME_INIT_SCRIPT,
  THEME_STORAGE_KEY,
  normalizeThemeChoice,
  resolveTheme,
} from "./theme.js";

const projectRoot = process.cwd();

function runInitScript({ stored, prefersDark = false, throws = false }) {
  const root = { dataset: {} };
  const localStorage = {
    getItem(key) {
      if (throws) throw new Error("blocked");
      return key === THEME_STORAGE_KEY ? stored : null;
    },
  };
  const window = {
    matchMedia(query) {
      assert.equal(query, DARK_MEDIA_QUERY);
      return { matches: prefersDark };
    },
  };
  new Function("localStorage", "window", "document", THEME_INIT_SCRIPT)(localStorage, window, {
    documentElement: root,
  });
  return root.dataset.theme;
}

test("theme choices are light, dark, and system", () => {
  assert.deepEqual(THEME_CHOICES, ["light", "dark", "system"]);
  assert.equal(THEME_STORAGE_KEY, "ga-theme");
});

test("normalizeThemeChoice falls back to system for unknown values", () => {
  assert.equal(normalizeThemeChoice("dark"), "dark");
  assert.equal(normalizeThemeChoice("light"), "light");
  assert.equal(normalizeThemeChoice("system"), "system");
  assert.equal(normalizeThemeChoice("purple"), "system");
  assert.equal(normalizeThemeChoice(null), "system");
});

test("resolveTheme follows the OS only in system mode", () => {
  assert.equal(resolveTheme("light", true), "light");
  assert.equal(resolveTheme("dark", false), "dark");
  assert.equal(resolveTheme("system", true), "dark");
  assert.equal(resolveTheme("system", false), "light");
  assert.equal(resolveTheme("bogus", true), "dark");
});

test("init script applies the stored choice before paint", () => {
  assert.equal(runInitScript({ stored: "dark" }), "dark");
  assert.equal(runInitScript({ stored: "light", prefersDark: true }), "light");
  assert.equal(runInitScript({ stored: null, prefersDark: true }), "dark");
  assert.equal(runInitScript({ stored: "nonsense", prefersDark: false }), "light");
});

test("init script never throws when storage is blocked", () => {
  assert.equal(runInitScript({ stored: "dark", throws: true }), undefined);
});

test("every light token has a dark-theme value", async () => {
  const css = await readFile(path.join(projectRoot, "app/globals.css"), "utf8");
  const block = (selector) => {
    const start = css.indexOf(`${selector} {`);
    assert.notEqual(start, -1, `missing ${selector} block`);
    return css.slice(start, css.indexOf("}", start));
  };
  const names = (text) => [...text.matchAll(/(--[a-z0-9-]+)\s*:/g)].map((match) => match[1]).sort();
  const light = names(block(":root"));
  assert.ok(light.includes("--surface") && light.includes("--brand"), "core tokens defined");
  assert.deepEqual(names(block('[data-theme="dark"]')), light);
});

function removeBlock(css, start) {
  const open = css.indexOf("{", start);
  let depth = 0;
  for (let index = open; index < css.length; index += 1) {
    if (css[index] === "{") depth += 1;
    if (css[index] === "}") depth -= 1;
    if (depth === 0) {
      return css.slice(0, start) + css.slice(index + 1);
    }
  }
  assert.fail("unbalanced braces in globals.css");
}

test("every rule outside the token blocks is layered so utilities can override it", async () => {
  const css = await readFile(path.join(projectRoot, "app/globals.css"), "utf8");
  assert.match(css, /@layer base \{/);
  assert.match(css, /@layer components \{/);

  let rest = css.replace(/\/\*[\s\S]*?\*\//g, "");
  for (let match = rest.match(/@layer [a-z-]+ \{/); match; match = rest.match(/@layer [a-z-]+ \{/)) {
    rest = removeBlock(rest, match.index);
  }
  for (const prelude of [":root {", '[data-theme="dark"] {', "@theme inline {"]) {
    const start = rest.indexOf(prelude);
    assert.notEqual(start, -1, `missing ${prelude} block`);
    rest = removeBlock(rest, start);
  }
  rest = rest.replace('@import "tailwindcss";', "");
  assert.equal(rest.trim(), "", `unlayered CSS found:\n${rest.trim()}`);
});

test("root layout loads Inter and injects the theme script", async () => {
  const layout = await readFile(path.join(projectRoot, "app/layout.js"), "utf8");
  assert.match(layout, /Inter\(/);
  assert.match(layout, /Roboto_Mono\(/);
  assert.match(layout, /suppressHydrationWarning/);
  assert.match(layout, /dangerouslySetInnerHTML=\{\{ __html: THEME_INIT_SCRIPT \}\}/);
  assert.doesNotMatch(layout, /Geist/);
});
