import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

const projectRoot = process.cwd();

function read(file) {
  return readFile(path.join(projectRoot, file), "utf8");
}

test("AnnotationExplorer lays out a results rail beside the detail pane", async () => {
  const explorer = await read("components/AnnotationExplorer.js");
  assert.match(explorer, /lg:grid-cols-\[320px_minmax\(0,1fr\)\]/);
  assert.match(explorer, /<ResultsRail/);
  assert.match(explorer, /<AnnotationDetail/);
  assert.match(explorer, /filterMatchesByOrganism\(matches, organism\)/);
});

test("selecting a result opens the Annotation tab", async () => {
  const explorer = await read("components/AnnotationExplorer.js");
  assert.match(explorer, /async function loadAnnotation\(annotationId\) \{[\s\S]*?setActiveTab\("annotation"\)/);
});

test("ortholog content gets its own tab only when the annotation has it", async () => {
  const detail = await read("components/annotations/AnnotationDetail.js");
  assert.match(detail, /const showOrtholog = hasOrthologColumn\(view\)/);
  assert.match(detail, /showOrtholog \? \[\{ id: "ortholog", label: "Ortholog" \}\] : \[\]/);
  const ortholog = await read("components/annotations/OrthologTab.js");
  assert.match(ortholog, /getOrthologGoTerms\(annotation\)/);
  assert.match(ortholog, /\.filter\(\(row\) => row\.orthologDerived\)/);
  assert.match(ortholog, /goTerms\.length > 0 \?/);
  assert.match(ortholog, /\{formatGoTermLabel\(term\)\}/);
});

test("annotations page uses the full-width shell", async () => {
  const page = await read("app/annotations/page.js");
  assert.match(page, /<AppShell fullWidth>/);
});
