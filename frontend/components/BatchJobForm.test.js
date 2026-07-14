import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

const projectRoot = process.cwd();

async function readProjectFile(relativePath) {
  return readFile(path.join(projectRoot, relativePath), "utf8");
}

test("batch job form supports validate preview and batch submit flow", async () => {
  const component = await readProjectFile("components/BatchJobForm.js");

  assert.match(component, /"use client";/);
  assert.match(component, /import \{ createBatch, validateBatch \} from "\.\.\/lib\/api";/);
  assert.match(component, /buildBatchPayload/);
  assert.match(component, /parseGeneFileName/);
  assert.match(component, /parseGeneListText/);
  assert.match(component, /readGeneFile/);
  assert.match(
    component,
    /One gene per line — locus \(e\.g\. Rv0001\) or gene name \(e\.g\. dnaA\)\. Commas and tabs also work\./,
  );
  assert.match(component, /accept="\.txt,\.csv,\.tsv"/);
  assert.match(component, /\.xlsx.*\.xls/s);
  assert.match(component, /Use \.txt, \.csv, or \.tsv — or paste from Excel/);
  assert.match(component, /parseGeneListText\(geneListText\)/);
  assert.match(component, /buildBatchPayload\(form, entries\)/);
  assert.match(component, /validateBatch\(payload\)/);
  assert.match(component, /createBatch\(payload\)/);
  assert.match(component, /onBatchSubmitted\(result\.batch_id, result\)/);
  assert.match(component, /readyCount >= 1 && ambiguousCount === 0/);
  assert.match(component, /duplicate_skipped} duplicate/);
  assert.match(component, /selected_locus: selected/);
  assert.match(component, /Choose locus…/);
});

test("batch job form exposes profile-only ortholog override controls", async () => {
  const component = await readProjectFile("components/BatchJobForm.js");

  assert.match(component, /Allow ortholog fallback/);
  assert.match(component, /updateForm\("allowOrthologFallback"/);
  assert.match(component, /Ortholog organism\/profile/);
  assert.match(component, /updateForm\("orthologProfile"/);
  assert.match(component, /A single ortholog gene cannot be reused across the batch/);
  assert.doesNotMatch(component, /Ortholog locus/);
  assert.doesNotMatch(component, /orthologLocus/);
  assert.doesNotMatch(component, /orthologName/);
});
