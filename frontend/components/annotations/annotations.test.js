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

test("tabs follow the WAI-ARIA tabs pattern", async () => {
  const tabs = await read("AnnotationTabs.js");
  assert.match(tabs, /role="tablist"/);
  assert.match(tabs, /role="tab"/);
  assert.match(tabs, /aria-selected=\{selected\}/);
  assert.match(tabs, /tabIndex=\{selected \? 0 : -1\}/);
  assert.match(tabs, /ArrowRight/);
  const detail = await read("AnnotationDetail.js");
  assert.match(detail, /role="tabpanel"/);
});

test("results rail focuses search on Cmd/Ctrl-K and keeps the submit-a-gene path", async () => {
  const rail = await read("ResultsRail.js");
  assert.match(rail, /\(event\.metaKey \|\| event\.ctrlKey\) && event\.key\.toLowerCase\(\) === "k"/);
  assert.match(rail, /href=\{`\/jobs\?locus=\$\{encodeURIComponent\(searchedQuery\)\}`\}/);
  assert.match(rail, /Submit this gene for annotation/);
});

test("disclaimer can be hidden for the browser session only", async () => {
  const header = await read("AnnotationHeader.js");
  assert.match(header, /sessionStorage/);
  assert.doesNotMatch(header, /localStorage/);
});

test("re-run is offered only on the latest version", async () => {
  const header = await read("AnnotationHeader.js");
  assert.match(header, /!viewingHistorical \? \(\s*<Link\s+href=\{buildJobPrefillHref\(annotation\)\}/);
});
