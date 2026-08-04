import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

async function readAnnotationExplorer() {
  return readFile(path.join(projectRoot, "components/AnnotationExplorer.js"), "utf8");
}

test("AnnotationContent builds target and ortholog columns from display helpers", async () => {
  const component = await readAnnotationExplorer();

  assert.match(component, /getTargetGoTerms/);
  assert.match(component, /getOrthologGoTerms/);
  assert.match(component, /hasOrthologColumn/);
  assert.match(component, /generatedRows\.filter\(\(row\) => !row\.orthologOnly\)/);
  assert.match(component, /generatedRows\.filter\(\(row\) => row\.orthologDerived\)/);
  assert.match(component, /showOrtholog \? "lg:grid-cols-2" : ""/);
  assert.match(component, /\{showOrtholog \? "Target" : "Generated annotation fields"\}/);
  assert.match(component, />\s*Ortholog\s*<\/h3>/);
  assert.match(component, /terms=\{targetGoTerms\}/);
  assert.match(component, /terms=\{orthologGoTerms\}/);
});

test("AnnotationContent hides empty GO sections and formats only id and name", async () => {
  const component = await readAnnotationExplorer();

  assert.match(component, /function GoTermList\(\{ terms \}\)/);
  assert.match(component, /if \(terms\.length === 0\) \{\s*return null;\s*\}/);
  assert.match(component, /\{formatGoTermLabel\(term\)\}/);
  assert.doesNotMatch(component, /term\.(agreement|confidence|votes)/);
});
