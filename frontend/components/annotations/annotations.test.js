import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

const projectRoot = process.cwd();

async function read(file) {
  return readFile(path.join(projectRoot, "components/annotations", file), "utf8");
}

test("OverviewTab places fields with planAnnotationGrid", async () => {
  const overview = await read("OverviewTab.js");
  assert.match(overview, /planAnnotationGrid\(getGeneratedFieldRows\(annotation, profileFields\)\)/);
  assert.match(overview, /full: "col-span-12"/);
  assert.match(overview, /half: "col-span-12 xl:col-span-6"/);
});

test("OverviewTab shows GO terms only when present, as name and id", async () => {
  const overview = await read("OverviewTab.js");
  assert.match(overview, /getTargetGoTerms\(annotation\)/);
  assert.match(overview, /goTerms\.length > 0 \? <GoTermsCard/);
  assert.match(overview, /\{term\.name\}/);
  assert.match(overview, /\{term\.id\}/);
});

test("annotation components never show GO confidence, agreement, or votes", async () => {
  const files = (await readdir(path.join(projectRoot, "components/annotations"))).filter(
    (file) => file.endsWith(".js") && !file.endsWith(".test.js"),
  );
  for (const file of files) {
    assert.doesNotMatch(await read(file), /term\.(agreement|confidence|votes)/, file);
  }
});

test("OverviewTab marks ortholog-derived fields", async () => {
  const overview = await read("OverviewTab.js");
  assert.match(overview, /row\.orthologDerived/);
  assert.match(overview, /"From ortholog"/);
});

test("CitedText links PMIDs to PubMed in a new tab", async () => {
  const cited = await read("CitedText.js");
  assert.match(cited, /splitCitations\(text\)/);
  assert.match(cited, /href=\{pubmedUrl\(segment\.value\)\}/);
  assert.match(cited, /rel="noopener noreferrer"/);
});
