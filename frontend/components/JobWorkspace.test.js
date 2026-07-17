import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

import { formatJobStepLabel, progressPercent } from "../lib/jobProgress.js";

const projectRoot = process.cwd();

async function readProjectFile(relativePath) {
  return readFile(path.join(projectRoot, relativePath), "utf8");
}

test("JobWorkspace integrates batch queue filtering and summary card", async () => {
  const workspace = await readProjectFile("components/JobWorkspace.js");

  assert.match(workspace, /filterJobsByBatch/);
  assert.match(workspace, /getBatch/);
  assert.match(workspace, /BatchSummaryCard/);
  assert.match(workspace, /setBatchFilterActive\(true\)/);
  assert.match(workspace, /Show batch only/);
  assert.match(workspace, /Show all jobs/);
});

test("completed job annotation link falls back to name and preflight identifiers", async () => {
  const workspace = await readProjectFile("components/JobWorkspace.js");

  assert.match(
    workspace,
    /const annotationQuery =\s*request\.locus \|\|\s*request\.name \|\|\s*request\.target_preflight\?\.resolved_name \|\|\s*request\.target_preflight\?\.primary_identifier \|\|\s*"";/s,
  );
  assert.match(
    workspace,
    /href=\{`\/annotations\?query=\$\{encodeURIComponent\(annotationQuery\)\}`\}/,
  );
});

test("JobWorkspace exposes an ortholog fallback checkbox and manual override inputs", async () => {
  const workspace = await readProjectFile("components/JobWorkspace.js");

  assert.match(workspace, /allowOrthologFallback: false/);
  assert.match(workspace, /Allow ortholog fallback/);
  assert.match(
    workspace,
    /updateForm\("allowOrthologFallback", event\.target\.checked\)/,
  );
  assert.match(workspace, /form\.allowOrthologFallback \?/);
  assert.match(workspace, /updateForm\("orthologProfile", event\.target\.value\)/);
  assert.match(workspace, /updateForm\("orthologLocus", event\.target\.value\)/);
  assert.match(workspace, /updateForm\("orthologName", event\.target\.value\)/);
  assert.match(
    workspace,
    /Choose a profile without a locus to restrict[\s\S]*automatic search to that organism/,
  );
});

test("JobWorkspace sources tile label and progress bar from lib/jobProgress", async () => {
  const workspace = await readProjectFile("components/JobWorkspace.js");

  assert.match(workspace, /from ["']\.\.\/lib\/jobProgress(?:\.js)?["']/);
  assert.match(workspace, /formatJobStepLabel\(job, stepLabels\)/);
  assert.match(workspace, /progressPercent\(job\)/);
});

test("JobWorkspace titles job tiles with getJobDisplayName", async () => {
  const workspace = await readProjectFile("components/JobWorkspace.js");

  assert.match(workspace, /getJobDisplayName/);
  assert.match(workspace, /getJobDisplayName\(job\)/);
  assert.doesNotMatch(
    workspace,
    /\{request\.name \|\| request\.locus \|\| "Unknown locus"\}/,
  );
});

test("job tile shows sections progress when structured fields present", () => {
  const label = formatJobStepLabel(
    {
      status: "running",
      progress_phase: "extracting",
      sections_done: 3,
      sections_total: 12,
      pass_name: "target",
      current_step: "extracting 3/12 sections (target)",
    },
    { running: "Annotator running" },
  );

  assert.match(label, /3\/12/);
  assert.match(label, /extracting/);
});

test("formatJobStepLabel falls back to legacy step labels without structured fields", () => {
  const stepLabels = { running: "Annotator running", queued: "Waiting in queue" };

  assert.equal(
    formatJobStepLabel({ status: "running", current_step: "queued" }, stepLabels),
    "Waiting in queue",
  );
  assert.equal(
    formatJobStepLabel({ status: "running", current_step: undefined }, stepLabels),
    "Annotator running",
  );
});

test("progressPercent maps target-only extraction after the 5% fetch placeholder", () => {
  // No ortholog progress has appeared yet. Fetching holds at 5%; extraction
  // fills the remaining 95%. 3/12 target → 5 + 95*(3/12) = 29%.
  assert.equal(
    progressPercent({
      status: "running",
      pass_name: "target",
      progress_phase: "fetching",
    }),
    5,
  );
  assert.equal(
    progressPercent({
      status: "running",
      pass_name: "target",
      sections_done: 0,
      sections_total: 12,
    }),
    5,
  );
  assert.equal(
    progressPercent({
      status: "running",
      pass_name: "target",
      sections_done: 3,
      sections_total: 12,
    }),
    29,
  );
});

test("progressPercent maps ortholog pass into second half of bar", () => {
  // ortholog 1/2 → 50 + 50*(1/2) = 75
  assert.equal(
    progressPercent({
      status: "running",
      pass_name: "ortholog",
      progress_phase: "ortholog_extracting",
      sections_done: 1,
      sections_total: 2,
    }),
    75,
  );
});

test("progressPercent holds at 50 while ortholog total unknown", () => {
  assert.equal(
    progressPercent({
      status: "running",
      pass_name: "ortholog",
      progress_phase: "ortholog_fetching",
      sections_done: 0,
      sections_total: null,
    }),
    50,
  );
});

test("progressPercent clamps running progress below 100 and completes at 100", () => {
  // 12/12 → 5 + 95 = 100, clamped to 99 while still running.
  assert.equal(
    progressPercent({
      status: "running",
      pass_name: "target",
      sections_done: 12,
      sections_total: 12,
    }),
    99,
  );
  assert.equal(
    progressPercent({ status: "completed", pass_name: "target", sections_done: 12, sections_total: 12 }),
    100,
  );
  assert.equal(progressPercent({ status: "failed" }), 100);
});

test("progressPercent falls back to coarse heuristic without structured fields", () => {
  assert.equal(progressPercent({ status: "queued" }), 12);
  assert.equal(progressPercent({ status: "running" }), 5);
  assert.equal(progressPercent({ status: "running", current_step: "saving_result" }), 85);
});
