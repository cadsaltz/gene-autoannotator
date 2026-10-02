"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { motion } from "framer-motion";

import BatchJobForm from "./BatchJobForm";
import SingleJobForm, { useJobForm } from "./SingleJobForm";
import {
  cancelJob,
  clearFinishedJobHistory,
  getAnnotationHealth,
  getBatch,
  getHealth,
  getProfiles,
  getQueueStatus,
  listJobs,
} from "../lib/api";
import { formatJobElapsed } from "../lib/form";
import {
  filterJobsByBatch,
  getAnnotationQuery,
  getHiddenJobCount,
  getJobDisplayName,
  getVisibleJobs,
  isCancellable,
  shouldShowRunningSpinner,
} from "../lib/jobQueue";
import { buildJobsHealthDisplay } from "../lib/healthFormat";
import { formatJobStepLabel, progressPercent } from "../lib/jobProgress";

function JobsHealthBanner({ health, annotationHealth }) {
  const display = buildJobsHealthDisplay(health, annotationHealth);
  const isOk = display.tone === "ok";

  return (
    <div
      className={`workbench-surface-bg rounded-xl border px-5 py-4 ${
        isOk ? "health-status-ok workbench-border" : "health-status-warn workbench-border-amber"
      }`}
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <p
            className={`text-base font-semibold tracking-tight ${
              isOk ? "workbench-green" : "workbench-amber"
            }`}
          >
            {display.title}
          </p>
          <p className="workbench-muted mt-1 text-sm leading-6">{display.message}</p>
          {display.extraCount > 0 ? (
            <p className="workbench-muted mt-1 text-xs leading-5">
              + {display.extraCount} more issue{display.extraCount === 1 ? "" : "s"} on the fleet
              page
            </p>
          ) : null}
        </div>
        <Link href="/fleet" className="workbench-green shrink-0 text-sm font-semibold hover:text-fg">
          Fleet &amp; health →
        </Link>
      </div>
    </div>
  );
}

const stepLabels = {
  queued: "Waiting in queue",
  running: "Annotator running",
  saving_result: "Saving result",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
};

function statusTone(status) {
  if (status === "completed") return "job-card-completed";
  if (status === "failed") return "job-card-failed";
  if (status === "running") return "job-card-running";
  if (status === "cancelled") return "job-card-cancelled";
  return "job-card-queued";
}

function summarizeJobStatuses(jobs) {
  const counts = { queued: 0, running: 0, completed: 0, failed: 0, cancelled: 0 };
  for (const job of jobs) {
    if (Object.hasOwn(counts, job.status)) {
      counts[job.status] += 1;
    }
  }
  return counts;
}

function BatchSummaryCard({ batchId, batchDetail, queueCounts, batchFilterActive, onShowBatchOnly, onShowAllJobs }) {
  const profileLabel =
    batchDetail?.profile ||
    batchDetail?.organism ||
    batchDetail?.strain ||
    "Batch annotation run";

  return (
    <div className="workbench-muted-bg rounded-xl border workbench-border p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="workbench-kicker">Active batch</p>
          <p className="workbench-foreground mt-1 text-lg font-semibold tracking-tight">{batchId}</p>
          <p className="workbench-muted mt-1 text-sm">{profileLabel}</p>
        </div>
        <span className="rounded-full border workbench-border bg-surface px-3 py-1 text-xs font-medium text-fg-secondary">
          {batchDetail?.status || "submitted"}
        </span>
      </div>

      <p className="workbench-muted mt-4 text-sm">
        {queueCounts.running || 0} running · {queueCounts.queued || 0} queued ·{" "}
        {queueCounts.completed || 0} completed · {queueCounts.failed || 0} failed ·{" "}
        {queueCounts.cancelled || 0} cancelled
      </p>

      <div
        className="mt-4 inline-flex rounded-xl border workbench-border p-1"
        role="group"
        aria-label="Batch queue filter"
      >
        <button
          type="button"
          onClick={onShowBatchOnly}
          aria-pressed={batchFilterActive}
          className={`min-h-9 rounded-lg px-3 text-sm font-semibold transition-colors ${
            batchFilterActive
              ? "workbench-button-primary"
              : "workbench-button-secondary border-0 bg-transparent shadow-none"
          }`}
        >
          Show batch only
        </button>
        <button
          type="button"
          onClick={onShowAllJobs}
          aria-pressed={!batchFilterActive}
          className={`min-h-9 rounded-lg px-3 text-sm font-semibold transition-colors ${
            !batchFilterActive
              ? "workbench-button-primary"
              : "workbench-button-secondary border-0 bg-transparent shadow-none"
          }`}
        >
          Show all jobs
        </button>
      </div>
    </div>
  );
}

function JobTile({ job, onCancel, cancelling }) {
  const elapsed = formatJobElapsed(job);
  const request = job.request || {};
  const annotationQuery = getAnnotationQuery(job);
  const step = formatJobStepLabel(job, stepLabels);
  const showSpinner = shouldShowRunningSpinner(job);

  return (
    <article className={`rounded-xl border workbench-border border-l-[5px] p-4 ${statusTone(job.status)}`}>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="workbench-foreground text-lg font-semibold tracking-tight">
            {getJobDisplayName(job)}
          </p>
          <p className="workbench-muted mt-1 text-sm">
            {request.profile || request.organism || "default profile"} · {request.locus}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {showSpinner ? (
            <motion.span
              aria-label="Annotation job running"
              className="inline-block size-4 rounded-full border-2 border-success-line border-t-brand-fg"
              animate={{ rotate: 360 }}
              transition={{ duration: 0.9, repeat: Infinity, ease: "linear" }}
            />
          ) : null}
          <span className="rounded-full border workbench-border bg-surface px-3 py-1 text-xs font-medium text-fg-secondary">
            {job.status}
          </span>
          {isCancellable(job) ? (
            <button
              type="button"
              onClick={() => onCancel(job)}
              disabled={cancelling}
              className="workbench-button workbench-button-secondary disabled:cursor-not-allowed disabled:opacity-50"
            >
              Cancel
            </button>
          ) : null}
        </div>
      </div>

      <div className="mt-4 h-2 overflow-hidden rounded-full bg-surface-sunken">
        <div
          className={`h-full rounded-full ${
            job.status === "failed"
              ? "bg-error-solid"
              : job.status === "cancelled"
                ? "bg-fg-subtle"
                : "bg-brand"
          }`}
          style={{ width: `${progressPercent(job)}%` }}
        />
      </div>

      <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-4">
        <div className="border-t workbench-border pt-2">
          <dt className="workbench-muted text-xs font-medium">Submitter</dt>
          <dd className="mt-1 break-all text-fg-secondary">{job.submitted_by_email || "Unknown"}</dd>
        </div>
        <div className="border-t workbench-border pt-2">
          <dt className="workbench-muted text-xs font-medium">Step</dt>
          <dd className="mt-1 text-fg-secondary">{step}</dd>
        </div>
        <div className="border-t workbench-border pt-2">
          <dt className="workbench-muted text-xs font-medium">Queue</dt>
          <dd className="mt-1 text-fg-secondary">
            {job.queue_position ? `#${job.queue_position}` : "Active or finished"}
          </dd>
        </div>
        <div className="border-t workbench-border pt-2">
          <dt className="workbench-muted text-xs font-medium">Elapsed</dt>
          <dd className="mt-1 text-fg-secondary">{elapsed}</dd>
        </div>
      </dl>

      {job.error ? <p className="workbench-red mt-4 text-sm">{job.error}</p> : null}
      {job.annotation_error ? (
        <p className="workbench-amber mt-4 text-sm">
          Annotation storage warning: {job.annotation_error}
        </p>
      ) : null}

      {job.result_available ? (
        <Link
          href={`/annotations?query=${encodeURIComponent(annotationQuery)}`}
          className="workbench-green mt-4 inline-flex text-sm font-semibold hover:text-fg"
        >
          Search stored annotation
        </Link>
      ) : null}
    </article>
  );
}

export default function JobWorkspace() {
  const [health, setHealth] = useState(null);
  const [annotationHealth, setAnnotationHealth] = useState(null);
  const [profiles, setProfiles] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [showAllJobs, setShowAllJobs] = useState(false);
  const [queue, setQueue] = useState({ queued: 0, running: 0, completed: 0, failed: 0, cancelled: 0 });
  const [statusMessage, setStatusMessage] = useState("");
  const [submissionsPaused, setSubmissionsPaused] = useState(false);
  const [submitMode, setSubmitMode] = useState("single");
  const [activeBatchId, setActiveBatchId] = useState(null);
  const [batchFilterActive, setBatchFilterActive] = useState(false);
  const [batchDetail, setBatchDetail] = useState(null);
  const [cancellingId, setCancellingId] = useState(null);
  const { form, updateForm, selectedProfile, isCustomProfile } = useJobForm(profiles);

  const apiAvailable = health?.status === "ok";
  const canSubmit = health !== null && apiAvailable;
  const queueJobs =
    activeBatchId && batchFilterActive ? filterJobsByBatch(jobs, activeBatchId) : jobs;
  const batchQueueCounts = useMemo(() => {
    if (batchDetail?.queue) {
      return batchDetail.queue;
    }
    if (activeBatchId) {
      return summarizeJobStatuses(filterJobsByBatch(jobs, activeBatchId));
    }
    return { queued: 0, running: 0, completed: 0, failed: 0, cancelled: 0 };
  }, [activeBatchId, batchDetail, jobs]);
  const hiddenJobCount = getHiddenJobCount(queueJobs);
  const visibleJobs = getVisibleJobs(queueJobs, showAllJobs);

  async function refreshHealth() {
    try {
      setHealth(await getHealth());
    } catch (error) {
      setHealth({
        status: "offline",
        stores: {},
        resources: { status: "unavailable", message: error.message },
      });
    }

    try {
      const queueStatus = await getQueueStatus();
      setSubmissionsPaused(queueStatus?.paused === true);
    } catch {
      setSubmissionsPaused(false);
    }

    try {
      setAnnotationHealth(await getAnnotationHealth());
    } catch (error) {
      setAnnotationHealth({
        status: "unavailable",
        message: error.message,
        source: "next",
      });
    }
  }

  async function refreshJobs({ updateStatusOnError = true } = {}) {
    try {
      const payload = await listJobs("queue");
      setJobs(payload.jobs || []);
      setQueue(payload.queue || {});
    } catch (error) {
      if (updateStatusOnError) {
        setStatusMessage(error.message);
      }
    }

    if (activeBatchId) {
      try {
        setBatchDetail(await getBatch(activeBatchId));
      } catch {
        setBatchDetail(null);
      }
    } else {
      setBatchDetail(null);
    }
  }

  useEffect(() => {
    async function loadInitialData() {
      await refreshHealth();
      try {
        const payload = await getProfiles();
        setProfiles(payload.profiles || []);
      } catch (error) {
        setStatusMessage(error.message);
      }
      await refreshJobs();
    }

    loadInitialData();
    // Polling keeps the UI simple while the job API is coarse. If the backend
    // later exposes precise progress or events, this is the main replacement
    // point for SSE/websocket-driven updates.
    const jobsTimer = window.setInterval(refreshJobs, 5000);
    const healthTimer = window.setInterval(refreshHealth, 15000);
    return () => {
      window.clearInterval(jobsTimer);
      window.clearInterval(healthTimer);
    };
  }, [activeBatchId]);

  async function handleCancel(job) {
    const confirmed = window.confirm(`Cancel the job for ${getJobDisplayName(job)}?`);
    if (!confirmed) {
      return;
    }

    setCancellingId(job.id);
    try {
      await cancelJob(job.id);
      setStatusMessage(`Cancelled job ${job.id}.`);
    } catch (error) {
      setStatusMessage(error.message);
    }
    try {
      await refreshJobs({ updateStatusOnError: false });
    } finally {
      setCancellingId(null);
    }
  }

  async function handleClearHistory() {
    const confirmed = window.confirm(
      "Clear completed, failed, and cancelled jobs from the history? Queued and running jobs will stay.",
    );
    if (!confirmed) {
      return;
    }

    try {
      const result = await clearFinishedJobHistory();
      setStatusMessage(`Cleared ${result.deleted} finished job${result.deleted === 1 ? "" : "s"}.`);
      await refreshJobs();
    } catch (error) {
      setStatusMessage(error.message);
    }
  }

  return (
    <div className="grid gap-5">
      <section>
        <div className="workbench-card flex min-h-64 flex-col justify-between p-6">
          <div>
            <p className="workbench-kicker">
              Backend
            </p>
            <h1 className="workbench-foreground mt-2 text-3xl font-semibold tracking-tight">
              Submit and monitor jobs
            </h1>
            <p className="workbench-muted mt-3 max-w-2xl text-sm leading-6">
              Choose a configured profile, enter a locus, and add the annotation run to the
              shared queue. Status stays visible beside the instructions so backend or storage
              problems are obvious before submitting work.
            </p>
          </div>
          <div className="mt-6 flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() => {
                refreshHealth();
                refreshJobs();
              }}
              className="workbench-button workbench-button-secondary"
            >
              Refresh
            </button>
          </div>
        </div>
      </section>

      <JobsHealthBanner health={health} annotationHealth={annotationHealth} />

      {submissionsPaused ? (
        <p className="workbench-amber-bg rounded-xl border workbench-border p-4 text-sm text-warning-fg">
          New submissions from non-admin users are paused (<code>SUBMISSIONS_PAUSED=1</code>).
          Queued and running jobs continue, and admins can still submit.
        </p>
      ) : null}

      <div className="grid items-start gap-5 lg:grid-cols-[0.95fr_1.05fr]">
        <section className="workbench-card p-6">
          <h2 className="text-2xl font-semibold tracking-tight">New annotation job</h2>
          <p className="workbench-muted mt-3 text-sm leading-6">
            Choose a configured profile, provide a gene name, locus, or both, and submit the run.
            Jobs are queued and executed sequentially; a real annotation can take hours.
          </p>

          <div
            className="mt-6 inline-flex rounded-xl border workbench-border p-1"
            role="group"
            aria-label="Submission mode"
          >
            <button
              type="button"
              onClick={() => setSubmitMode("single")}
              aria-pressed={submitMode === "single"}
              className={`min-h-10 rounded-lg px-4 text-sm font-semibold transition-colors ${
                submitMode === "single"
                  ? "workbench-button-primary"
                  : "workbench-button-secondary border-0 bg-transparent shadow-none"
              }`}
            >
              Single gene
            </button>
            <button
              type="button"
              onClick={() => setSubmitMode("batch")}
              aria-pressed={submitMode === "batch"}
              className={`min-h-10 rounded-lg px-4 text-sm font-semibold transition-colors ${
                submitMode === "batch"
                  ? "workbench-button-primary"
                  : "workbench-button-secondary border-0 bg-transparent shadow-none"
              }`}
            >
              Batch
            </button>
          </div>

          {submitMode === "single" ? (
            <SingleJobForm
              form={form}
              updateForm={updateForm}
              profiles={profiles}
              selectedProfile={selectedProfile}
              isCustomProfile={isCustomProfile}
              canSubmit={canSubmit}
              statusMessage={statusMessage}
              setStatusMessage={setStatusMessage}
              onJobQueued={() => refreshJobs({ updateStatusOnError: false })}
            />
          ) : (
            <div className="mt-6 grid gap-4">
              <BatchJobForm
                form={form}
                updateForm={updateForm}
                profiles={profiles}
                selectedProfile={selectedProfile}
                isCustomProfile={isCustomProfile}
                canSubmit={canSubmit}
                setStatusMessage={setStatusMessage}
                onBatchSubmitted={(batchId, result) => {
                  setActiveBatchId(batchId);
                  setBatchFilterActive(true);
                  const jobCount = result.job_ids?.length ?? 0;
                  setStatusMessage(
                    `Queued batch ${batchId} with ${jobCount} annotation${jobCount === 1 ? "" : "s"}.`,
                  );
                  refreshJobs();
                }}
              />

              {statusMessage ? (
                <p className="workbench-amber-bg rounded-xl border workbench-border p-4 text-sm text-warning-fg">
                  {statusMessage}
                </p>
              ) : null}
            </div>
          )}
        </section>

        <section className="workbench-card p-6">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h2 className="workbench-foreground text-2xl font-semibold tracking-tight">Job queue</h2>
              <p className="workbench-muted w-full md:w-35 mt-2 text-sm">
                {queue.running || 0} running · {queue.queued || 0} queued ·{" "}
                {queue.completed || 0} completed · {queue.failed || 0} failed ·{" "}
                {queue.cancelled || 0} cancelled
              </p>
            </div>
            <div className="flex flex-row flex-nowrap items-center gap-2 sm:justify-end">
              {hiddenJobCount > 0 ? (
                <button
                  type="button"
                  onClick={() => setShowAllJobs((current) => !current)}
                  className="workbench-button workbench-button-secondary w-52 shrink-0"
                >
                  {showAllJobs ? "Hide extra jobs" : `Show all jobs (${hiddenJobCount} more)`}
                </button>
              ) : null}
              <button
                type="button"
                onClick={handleClearHistory}
                disabled={(queue.completed || 0) + (queue.failed || 0) + (queue.cancelled || 0) === 0}
                suppressHydrationWarning
                className="workbench-button workbench-button-secondary disabled:cursor-not-allowed disabled:opacity-50"
              >
                Clear finished history
              </button>
            </div>
          </div>

          {activeBatchId ? (
            <div className="mt-6">
              <BatchSummaryCard
                batchId={activeBatchId}
                batchDetail={batchDetail}
                queueCounts={batchQueueCounts}
                batchFilterActive={batchFilterActive}
                onShowBatchOnly={() => setBatchFilterActive(true)}
                onShowAllJobs={() => setBatchFilterActive(false)}
              />
            </div>
          ) : null}

          <div className="mt-6 grid gap-4">
            {queueJobs.length > 0 ? (
              visibleJobs.map((job) => (
                <JobTile
                  key={job.id}
                  job={job}
                  onCancel={handleCancel}
                  cancelling={cancellingId === job.id}
                />
              ))
            ) : (
              <div className="workbench-muted rounded-xl border border-dashed workbench-border p-8 text-center">
                {activeBatchId && batchFilterActive
                  ? "No jobs in this batch yet."
                  : "No jobs have been submitted yet."}
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
