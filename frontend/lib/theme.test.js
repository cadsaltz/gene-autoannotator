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

test("component vocabulary lives in the components layer so utilities can override it", async () => {
  const css = await readFile(path.join(projectRoot, "app/globals.css"), "utf8");
  const marker = css.indexOf("@layer components {");
  assert.notEqual(marker, -1, "missing @layer components block");
  assert.doesNotMatch(css.slice(0, marker), /\.workbench-/);
});

test("root layout loads Inter and injects the theme script", async () => {
  const layout = await readFile(path.join(projectRoot, "app/layout.js"), "utf8");
  assert.match(layout, /Inter\(/);
  assert.match(layout, /Roboto_Mono\(/);
  assert.match(layout, /suppressHydrationWarning/);
  assert.match(layout, /dangerouslySetInnerHTML=\{\{ __html: THEME_INIT_SCRIPT \}\}/);
  assert.doesNotMatch(layout, /Geist/);
});
