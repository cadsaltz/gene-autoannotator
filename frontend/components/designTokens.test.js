import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

const projectRoot = process.cwd();
const SKIPPED = new Set();

const HARD_CODED_COLOUR =
  /\[#[0-9a-fA-F]{3,8}\]|\b(?:bg|text|border|from|to|ring|divide)-(?:slate|gray|zinc|stone|neutral|black)\b[-\w/]*|\bbg-white\b[\w/]*/g;
const OFF_SYSTEM_TYPE_AND_RADIUS =
  /\bfont-(?:bold|extrabold|black)\b|\btracking-\[[^\]]+\]|\buppercase\b|\brounded-(?:2xl|3xl|\[[^\]]+\])/g;

async function sourceFiles(dir) {
  const entries = await readdir(path.join(projectRoot, dir), { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const relative = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...(await sourceFiles(relative)));
    } else if (entry.name.endsWith(".js") && !entry.name.endsWith(".test.js")) {
      files.push(relative);
    }
  }
  return files;
}

async function offenders(pattern) {
  const files = [...(await sourceFiles("app")), ...(await sourceFiles("components"))];
  const found = [];
  for (const file of files) {
    if (SKIPPED.has(file)) continue;
    const source = await readFile(path.join(projectRoot, file), "utf8");
    const hits = source.match(pattern);
    if (hits) found.push(`${file}: ${[...new Set(hits)].join(", ")}`);
  }
  return found;
}

test("components use theme tokens instead of hard-coded colours", async () => {
  assert.deepEqual(await offenders(HARD_CODED_COLOUR), []);
});

test("components stay on the Untitled UI type scale and radii", async () => {
  assert.deepEqual(await offenders(OFF_SYSTEM_TYPE_AND_RADIUS), []);
});
