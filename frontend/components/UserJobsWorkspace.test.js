import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

import {
  describeSubmitError,
  describeUserSubmitError,
  formatQueuedCount,
  formatUsage,
} from "../lib/queueStatus.js";

const FLEET_OR_HEALTH = /getHealth|getWorkers|getAnnotationHealth|\/fleet/;

const projectRoot = process.cwd();

async function readProjectFile(relativePath) {
  return readFile(path.join(projectRoot, relativePath), "utf8");
}

test("UserJobsWorkspace reads queue status and own jobs, never fleet or health data", async () => {
  const workspace = await readProjectFile("components/UserJobsWorkspace.js");

  assert.match(workspace, /"use client";/);
  assert.match(workspace, /getQueueStatus/);
  assert.match(workspace, /listJobs\(/);
  assert.match(workspace, /cancelJob\(/);
  assert.doesNotMatch(workspace, /getHealth/);
  assert.doesNotMatch(workspace, /getWorkers/);
  assert.doesNotMatch(workspace, /getAnnotationHealth/);
  assert.doesNotMatch(workspace, /clearFinishedJobHistory/);
  assert.doesNotMatch(workspace, /\/fleet/);
  assert.doesNotMatch(workspace, /JobsHealthBanner|healthFormat/);
});

test("components rendered on the user jobs page never touch fleet or health data", async () => {
  for (const file of [
    "components/SingleJobForm.js",
    "components/BatchJobForm.js",
    "components/QueuePlaceholder.js",
  ]) {
    assert.doesNotMatch(await readProjectFile(file), FLEET_OR_HEALTH, file);
  }
});

test("UserJobsWorkspace describes submit errors with the user variant", async () => {
  const workspace = await readProjectFile("components/UserJobsWorkspace.js");

  assert.match(workspace, /describeUserSubmitError/);
  assert.match(workspace, /<SingleJobForm[\s\S]*?describeError=\{describeUserSubmitError\}/);
  assert.match(workspace, /<BatchJobForm[\s\S]*?describeError=\{describeUserSubmitError\}/);
});

test("submit forms accept describeError and default to the admin description", async () => {
  for (const file of ["components/SingleJobForm.js", "components/BatchJobForm.js"]) {
    const component = await readProjectFile(file);
    assert.match(component, /describeError = describeSubmitError/, file);
    assert.match(component, /setStatusMessage\(describeError\(error\)\)/, file);
  }
});

test("UserJobsWorkspace shows a generic message for failed jobs instead of worker errors", async () => {
  const workspace = await readProjectFile("components/UserJobsWorkspace.js");

  assert.match(workspace, /This job failed\. You can resubmit it\./);
  assert.doesNotMatch(workspace, /job\.error/);
  assert.doesNotMatch(workspace, /annotation_error/);
});

test("UserJobsWorkspace skips overlapping polls and state updates after unmount", async () => {
  const workspace = await readProjectFile("components/UserJobsWorkspace.js");

  assert.match(workspace, /const refreshInFlight = useRef\(false\)/);
  assert.match(workspace, /const mountedRef = useRef\(false\)/);
  assert.match(workspace, /if \(refreshInFlight\.current\)/);
  assert.match(workspace, /if \(!mountedRef\.current\)/);
  assert.match(workspace, /mountedRef\.current = false;/);
});

test("UserJobsWorkspace explains paused submissions when queue status fails to load", async () => {
  const workspace = await readProjectFile("components/UserJobsWorkspace.js");

  assert.match(workspace, /queueStatusFailed && !queueStatus/);
  assert.match(workspace, /Submissions are paused until the queue status loads/);
});

test("UserJobsWorkspace reuses the shared single and batch submit forms", async () => {
  const workspace = await readProjectFile("components/UserJobsWorkspace.js");

  assert.match(workspace, /import BatchJobForm from "\.\/BatchJobForm";/);
  assert.match(workspace, /import SingleJobForm, \{[^}]*useJobForm[^}]*\} from "\.\/SingleJobForm";/);
  assert.match(workspace, /<SingleJobForm/);
  assert.match(workspace, /<BatchJobForm/);
});

test("UserJobsWorkspace polls every 15 seconds and refreshes after submit and cancel", async () => {
  const workspace = await readProjectFile("components/UserJobsWorkspace.js");

  assert.match(workspace, /window\.setInterval\(refresh, 15000\)/);
  assert.match(workspace, /window\.clearInterval\(/);
  assert.match(workspace, /await cancelJob\(job\.id\);\s*await refresh\(\);/);
  assert.match(workspace, /onJobQueued=\{refresh\}/);
  assert.match(workspace, /onBatchSubmitted=\{[\s\S]*?refresh\(\);/);
});

test("UserJobsWorkspace disables submission while the queue is not accepting", async () => {
  const workspace = await readProjectFile("components/UserJobsWorkspace.js");

  assert.match(workspace, /const accepting = queueStatus\?\.accepting === true;/);
  assert.match(workspace, /Submissions are paused/);
  assert.match(workspace, /canSubmit=\{accepting\}/);
});

test("UserJobsWorkspace shows the queue placeholder, usage, and a private jobs table", async () => {
  const workspace = await readProjectFile("components/UserJobsWorkspace.js");

  assert.match(workspace, /<QueuePlaceholder status=\{queueStatus\} \/>/);
  assert.match(workspace, /Your usage/);
  assert.match(workspace, /formatUsage\(queueStatus\.your_active, queueStatus\.your_active_limit\)/);
  assert.match(workspace, /formatUsage\(queueStatus\.your_today, queueStatus\.your_daily_limit\)/);
  assert.match(workspace, /queueStatus\.batch_limit/);
  assert.match(workspace, /My jobs/);
  assert.match(workspace, /Gene \/ locus/);
  assert.match(workspace, /Submitted/);
  assert.match(workspace, /getJobDisplayName\(job\)/);
  assert.match(workspace, /getAnnotationQuery\(job\)/);
  assert.match(workspace, /href=\{`\/annotations\?query=\$\{encodeURIComponent\(/);
  assert.match(workspace, /isCancellable\(job\)/);
  assert.match(workspace, />\s*Cancel\s*</);
});

test("QueuePlaceholder shows only the queued count and whether submissions are open", async () => {
  const placeholder = await readProjectFile("components/QueuePlaceholder.js");

  assert.match(placeholder, /formatQueuedCount\(status\.queued\)/);
  assert.match(placeholder, /Submissions open/);
  assert.match(placeholder, /Submissions paused/);
  assert.doesNotMatch(placeholder, /from "\.\.\/lib\/api"/);
});

test("formatQueuedCount pluralizes the global queued count", () => {
  assert.equal(formatQueuedCount(0), "0 jobs queued");
  assert.equal(formatQueuedCount(1), "1 job queued");
  assert.equal(formatQueuedCount(12), "12 jobs queued");
  assert.equal(formatQueuedCount(undefined), "0 jobs queued");
});

test("formatUsage shows used / limit and handles unlimited quotas", () => {
  assert.equal(formatUsage(2, 5), "2 / 5");
  assert.equal(formatUsage(0, 0), "0 / 0");
  assert.equal(formatUsage(3, null), "3 (no limit)");
  assert.equal(formatUsage(undefined, 4), "0 / 4");
});

test("describeSubmitError surfaces the backend detail for quota errors", () => {
  const quota = Object.assign(new Error("You can have at most 3 queued or running jobs."), {
    status: 429,
    code: "active_limit",
  });
  assert.equal(describeSubmitError(quota), "You can have at most 3 queued or running jobs.");

  const plain = Object.assign(new Error("Profile not found"), { status: 404, code: null });
  assert.equal(describeSubmitError(plain), "Profile not found");
});

test("describeSubmitError falls back to a code-specific message when detail is missing", () => {
  const generic = (code) =>
    Object.assign(new Error("Backend returned HTTP 429"), { status: 429, code });

  assert.match(describeSubmitError(generic("queue_full")), /queue is full/i);
  assert.match(describeSubmitError(generic("active_limit")), /active/i);
  assert.match(describeSubmitError(generic("daily_limit")), /24 hours|daily/i);
  assert.match(describeSubmitError(generic("batch_limit")), /batch/i);
  assert.match(describeSubmitError(generic("rate_limited")), /too many/i);
  assert.match(describeSubmitError(generic(null)), /try again/i);
});

test("describeSubmitError hides service-unavailable detail from non-admins", () => {
  const unavailable = Object.assign(new Error("No workers connected with job capacity."), {
    status: 503,
    code: null,
  });

  assert.equal(describeSubmitError(unavailable), "No workers connected with job capacity.");
  assert.equal(
    describeSubmitError(unavailable, { admin: true }),
    "No workers connected with job capacity.",
  );
  for (const message of [
    describeSubmitError(unavailable, { admin: false }),
    describeUserSubmitError(unavailable),
  ]) {
    assert.doesNotMatch(message, /worker/i);
    assert.match(message, /try again later/i);
  }

  const quota = Object.assign(new Error("You can submit at most 5 jobs per 24 hours."), {
    status: 429,
    code: "daily_limit",
  });
  assert.equal(describeUserSubmitError(quota), "You can submit at most 5 jobs per 24 hours.");
});

test("BatchJobForm imports the admin describeSubmitError as its default", async () => {
  const component = await readProjectFile("components/BatchJobForm.js");

  assert.match(component, /import \{ describeSubmitError \} from "\.\.\/lib\/queueStatus";/);
});

test("jobs page picks the workspace by role on the server", async () => {
  const page = await readProjectFile("app/jobs/page.js");

  assert.doesNotMatch(page, /"use client"/);
  assert.match(page, /await getServerSession\(\)/);
  assert.match(page, /redirect\("\/login\?next=\/jobs"\)/);
  assert.match(page, /role === "admin"/);
  assert.match(page, /<JobWorkspace \/>/);
  assert.match(page, /<UserJobsWorkspace \/>/);
});

test("admin JobWorkspace can cancel queued and running jobs and counts cancelled jobs", async () => {
  const workspace = await readProjectFile("components/JobWorkspace.js");

  assert.match(workspace, /cancelJob/);
  assert.match(workspace, /isCancellable\(job\)/);
  assert.match(workspace, /const \[cancellingId, setCancellingId\] = useState\(null\)/);
  assert.match(workspace, /cancelling=\{cancellingId === job\.id\}/);
  assert.match(workspace, /disabled=\{cancelling\}/);
  assert.match(workspace, /finally \{\s*setCancellingId\(null\);/);
  assert.match(workspace, />\s*Cancel\s*</);
  assert.match(workspace, /cancelled: 0/);
  assert.match(workspace, /queue\.cancelled/);
  assert.match(workspace, /job-card-cancelled/);
});

test("describeUserSubmitError shows the backend detail when submissions are paused", () => {
  const paused = Object.assign(new Error("New submissions are paused. Please try again later."), {
    status: 503,
    code: "paused",
  });
  assert.equal(describeUserSubmitError(paused), "New submissions are paused. Please try again later.");
  assert.equal(describeSubmitError(paused), "New submissions are paused. Please try again later.");

  const bare = Object.assign(new Error("Backend returned HTTP 503"), { status: 503, code: "paused" });
  assert.match(describeUserSubmitError(bare), /paused/i);

  const unavailable = Object.assign(new Error("No workers connected with job capacity."), {
    status: 503,
    code: "unavailable",
  });
  assert.doesNotMatch(describeUserSubmitError(unavailable), /worker/i);
});

test("UserJobsWorkspace distinguishes an operator pause from a full queue", async () => {
  const workspace = await readProjectFile("components/UserJobsWorkspace.js");

  assert.match(workspace, /queueStatus\.paused/);
  assert.match(workspace, /New submissions are paused/);
  assert.match(workspace, /Submissions are paused because the shared queue is full/);
});
