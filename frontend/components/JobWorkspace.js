"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { motion } from "framer-motion";

import BatchJobForm from "./BatchJobForm";
import {
  clearFinishedJobHistory,
  createJob,
  getAnnotationHealth,
  getBatch,
  getHealth,
  getProfiles,
  listJobs,
  validateJob,
} from "../lib/api";
import {
  buildJobPayload,
  formatJobElapsed,
} from "../lib/form";
import {
  filterJobsByBatch,
  getHiddenJobCount,
  getVisibleJobs,
  shouldShowRunningSpinner,
} from "../lib/jobQueue";
import { buildJobsHealthDisplay } from "../lib/healthFormat";
import { formatJobStepLabel, progressPercent } from "../lib/jobProgress";

function JobsHealthBanner({ health, annotationHealth }) {
  const display = buildJobsHealthDisplay(health, annotationHealth);
  const isOk = display.tone === "ok";

  return (
    <div
      className={`workbench-surface-bg rounded-2xl border px-5 py-4 ${
        isOk ? "health-status-ok workbench-border" : "health-status-warn workbench-border-amber"
      }`}
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <p
            className={`text-base font-bold tracking-[-0.02em] ${
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
        <Link href="/fleet" className="workbench-green shrink-0 text-sm font-bold hover:text-[#111a16]">
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
};

const emptyCustomFields = {
  organism: "",
  strain: "",
  locusRegex: "",
  searchTerms: "",
  targetPatterns: "",
  offTargetPatterns: "",
  excludedSpeciesPatterns: "",
};

function statusTone(status) {
  if (status === "completed") return "job-card-completed";
  if (status === "failed") return "job-card-failed";
  if (status === "running") return "job-card-running";
  return "job-card-queued";
}

function summarizeJobStatuses(jobs) {
  const counts = { queued: 0, running: 0, completed: 0, failed: 0 };
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
    <div className="workbench-muted-bg rounded-2xl border workbench-border p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="workbench-kicker">Active batch</p>
          <p className="workbench-foreground mt-1 text-lg font-bold tracking-[-0.02em]">{batchId}</p>
          <p className="workbench-muted mt-1 text-sm">{profileLabel}</p>
        </div>
        <span className="rounded-full border workbench-border bg-white/60 px-3 py-1 text-xs font-bold uppercase tracking-wide text-[#3f4b43]">
          {batchDetail?.status || "submitted"}
        </span>
      </div>

      <p className="workbench-muted mt-4 text-sm">
        {queueCounts.running || 0} running · {queueCounts.queued || 0} queued ·{" "}
        {queueCounts.completed || 0} completed · {queueCounts.failed || 0} failed
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
          className={`min-h-9 rounded-lg px-3 text-sm font-bold transition-colors ${
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
          className={`min-h-9 rounded-lg px-3 text-sm font-bold transition-colors ${
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

function JobTile({ job }) {
  const elapsed = formatJobElapsed(job);
  const request = job.request || {};
  const annotationQuery =
    request.locus ||
    request.name ||
    request.target_preflight?.resolved_name ||
    request.target_preflight?.primary_identifier ||
    "";
  const step = formatJobStepLabel(job, stepLabels);
  const showSpinner = shouldShowRunningSpinner(job);

  return (
    <article className={`rounded-2xl border workbench-border border-l-[5px] p-4 ${statusTone(job.status)}`}>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="workbench-foreground text-lg font-bold tracking-[-0.02em]">
            {request.name || request.locus || "Unknown locus"}
          </p>
          <p className="workbench-muted mt-1 text-sm">
            {request.profile || request.organism || "default profile"} · {request.locus}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {showSpinner ? (
            <motion.span
              aria-label="Annotation job running"
              className="inline-block size-4 rounded-full border-2 border-[#b8c7bb] border-t-[#557864]"
              animate={{ rotate: 360 }}
              transition={{ duration: 0.9, repeat: Infinity, ease: "linear" }}
            />
          ) : null}
          <span className="rounded-full border workbench-border bg-white/60 px-3 py-1 text-xs font-bold uppercase tracking-wide text-[#3f4b43]">
            {job.status}
          </span>
        </div>
      </div>

      <div className="mt-4 h-2 overflow-hidden rounded-full bg-[#e3dbcf]">
        <div
          className={`h-full rounded-full ${
            job.status === "failed" ? "bg-[#994f56]" : "bg-[#557864]"
          }`}
          style={{ width: `${progressPercent(job)}%` }}
        />
      </div>

      <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-3">
        <div className="border-t workbench-border pt-2">
          <dt className="workbench-muted text-xs font-bold uppercase tracking-[0.1em]">Step</dt>
          <dd className="mt-1 text-[#3d463f]">{step}</dd>
        </div>
        <div className="border-t workbench-border pt-2">
          <dt className="workbench-muted text-xs font-bold uppercase tracking-[0.1em]">Queue</dt>
          <dd className="mt-1 text-[#3d463f]">
            {job.queue_position ? `#${job.queue_position}` : "Active or finished"}
          </dd>
        </div>
        <div className="border-t workbench-border pt-2">
          <dt className="workbench-muted text-xs font-bold uppercase tracking-[0.1em]">Elapsed</dt>
          <dd className="mt-1 text-[#3d463f]">{elapsed}</dd>
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
          className="workbench-green mt-4 inline-flex text-sm font-bold hover:text-[#111a16]"
        >
          Search stored annotation
        </Link>
      ) : null}
    </article>
  );
}

export default function JobWorkspace() {
  const searchParams = useSearchParams();
  const [health, setHealth] = useState(null);
  const [annotationHealth, setAnnotationHealth] = useState(null);
  const [profiles, setProfiles] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [showAllJobs, setShowAllJobs] = useState(false);
  const [queue, setQueue] = useState({ queued: 0, running: 0, completed: 0, failed: 0 });
  const [statusMessage, setStatusMessage] = useState("");
  const [submitMode, setSubmitMode] = useState("single");
  const [activeBatchId, setActiveBatchId] = useState(null);
  const [batchFilterActive, setBatchFilterActive] = useState(false);
  const [batchDetail, setBatchDetail] = useState(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [form, setForm] = useState({
    profile: searchParams.get("profile") || "mtb-h37rv",
    organism: "",
    strain: "",
    locus: searchParams.get("locus") || "",
    name: searchParams.get("name") || "",
    allowOnlineNameLookup: true,
    refreshGeneNameCache: false,
    cacheSuppliedName: false,
    allowOrthologFallback: false,
    orthologProfile: "",
    orthologLocus: "",
    orthologName: "",
    locusRegex: "",
    searchTerms: "",
    targetPatterns: "",
    offTargetPatterns: "",
    excludedSpeciesPatterns: "",
  });

  const apiAvailable = health?.status === "ok";
  const canSubmit = health !== null && apiAvailable && !isSubmitting;
  const queueJobs =
    activeBatchId && batchFilterActive ? filterJobsByBatch(jobs, activeBatchId) : jobs;
  const batchQueueCounts = useMemo(() => {
    if (batchDetail?.queue) {
      return batchDetail.queue;
    }
    if (activeBatchId) {
      return summarizeJobStatuses(filterJobsByBatch(jobs, activeBatchId));
    }
    return { queued: 0, running: 0, completed: 0, failed: 0 };
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

  const selectedProfile = useMemo(
    () => profiles.find((profile) => profile.profile_id === form.profile),
    [profiles, form.profile],
  );
  const isCustomProfile = form.profile === "";

  function updateForm(field, value) {
    setForm((current) => {
      if (field === "profile" && value !== "") {
        return { ...current, ...emptyCustomFields, profile: value };
      }
      return { ...current, [field]: value };
    });
  }

  async function handleSubmit(event) {
    event.preventDefault();
    setStatusMessage("");
    setIsSubmitting(true);

    try {
      const payload = buildJobPayload(form);
      if (!payload.locus && !payload.name) {
        throw new Error("Gene name or locus is required.");
      }
      const validation = await validateJob(payload);
      if (!validation.valid) {
        throw new Error("The target could not be submitted.");
      }
      const created = await createJob(payload);
      const warningText = validation.warnings?.length
        ? ` Warnings: ${validation.warnings.map((warning) => warning.message).join(" ")}`
        : "";
      setStatusMessage(`Queued job ${created.job_id}. It will run when earlier jobs finish.${warningText}`);
      await refreshJobs({ updateStatusOnError: false });
    } catch (error) {
      setStatusMessage(error.message);
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleClearHistory() {
    const confirmed = window.confirm(
      "Clear completed and failed jobs from the history? Queued and running jobs will stay.",
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
            <h1 className="workbench-foreground mt-2 text-3xl font-bold tracking-[-0.04em]">
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

      <div className="grid items-start gap-5 lg:grid-cols-[0.95fr_1.05fr]">
        <section className="workbench-card p-6">
          <h2 className="text-2xl font-bold tracking-[-0.03em]">New annotation job</h2>
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
              className={`min-h-10 rounded-lg px-4 text-sm font-bold transition-colors ${
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
              className={`min-h-10 rounded-lg px-4 text-sm font-bold transition-colors ${
                submitMode === "batch"
                  ? "workbench-button-primary"
                  : "workbench-button-secondary border-0 bg-transparent shadow-none"
              }`}
            >
              Batch
            </button>
          </div>

          {submitMode === "single" ? (
          <form className="mt-6 grid gap-4" onSubmit={handleSubmit}>
            <label className="grid gap-2 text-sm font-medium">
              Profile
              <select
                value={form.profile}
                onChange={(event) => updateForm("profile", event.target.value)}
                className="workbench-input"
              >
                <option value="">Custom organism/strain</option>
                {profiles.map((profile) => (
                  <option key={profile.profile_id} value={profile.profile_id}>
                    {profile.canonical_name}
                  </option>
                ))}
              </select>
            </label>

            {!isCustomProfile && selectedProfile ? (
              <div className="workbench-muted-bg workbench-muted rounded-xl border workbench-border p-4 text-sm">
                Expected locus format:{" "}
                <code className="rounded bg-[#eee6d9] px-1 py-0.5">
                  {selectedProfile.locus_regex}
                </code>
              </div>
            ) : null}

            {isCustomProfile ? (
              <div className="grid gap-4 sm:grid-cols-2">
                <label className="grid gap-2 text-sm font-medium">
                  Organism
                  <input
                    value={form.organism}
                    onChange={(event) => updateForm("organism", event.target.value)}
                    className="workbench-input"
                    placeholder="Trypanosoma cruzi"
                  />
                </label>
                <label className="grid gap-2 text-sm font-medium">
                  Strain
                  <input
                    value={form.strain}
                    onChange={(event) => updateForm("strain", event.target.value)}
                    className="workbench-input"
                    placeholder="CL Brener"
                  />
                </label>
              </div>
            ) : null}

            <label className="grid gap-2 text-sm font-medium">
              Locus (optional if gene name is supplied)
              <input
                value={form.locus}
                onChange={(event) => updateForm("locus", event.target.value)}
                className="workbench-input"
                placeholder="Rv0001 or TcCLB.503799.4"
              />
            </label>

            <label className="grid gap-2 text-sm font-medium">
              Gene name (optional if locus is supplied)
              <input
                value={form.name}
                onChange={(event) => updateForm("name", event.target.value)}
                className="workbench-input"
                placeholder="dnaA"
              />
            </label>

            <div className="workbench-muted-bg grid gap-3 rounded-xl border workbench-border p-4 text-sm">
              <label className="flex items-center gap-3">
                <input
                  type="checkbox"
                  checked={form.allowOnlineNameLookup}
                  onChange={(event) => updateForm("allowOnlineNameLookup", event.target.checked)}
                />
                Allow online gene-name lookup
              </label>
              <label className="flex items-center gap-3">
                <input
                  type="checkbox"
                  checked={form.refreshGeneNameCache}
                  onChange={(event) => updateForm("refreshGeneNameCache", event.target.checked)}
                />
                Refresh gene-name cache
              </label>
              <label className="flex items-center gap-3">
                <input
                  type="checkbox"
                  checked={form.cacheSuppliedName}
                  onChange={(event) => updateForm("cacheSuppliedName", event.target.checked)}
                />
                Cache supplied gene name
              </label>
              <label className="flex items-center gap-3">
                <input
                  type="checkbox"
                  checked={form.allowOrthologFallback}
                  onChange={(event) => updateForm("allowOrthologFallback", event.target.checked)}
                />
                Allow ortholog fallback
              </label>
            </div>

            {form.allowOrthologFallback ? (
              <div className="workbench-muted-bg grid gap-4 rounded-xl border workbench-border p-4 text-sm">
                <p className="workbench-muted">
                  Leave the ortholog fields blank for automatic ortholog lookup across
                  all profiled organisms. Choose a profile without a locus to restrict
                  automatic search to that organism. Supply a locus to pin a specific
                  ortholog gene.
                </p>
                <label className="grid gap-2 font-medium">
                  Ortholog organism/profile
                  <select
                    value={form.orthologProfile}
                    onChange={(event) => updateForm("orthologProfile", event.target.value)}
                    className="workbench-input"
                  >
                    <option value="">Automatic (any profiled organism)</option>
                    {profiles.map((profile) => (
                      <option key={profile.profile_id} value={profile.profile_id}>
                        {profile.canonical_name}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="grid gap-2 font-medium">
                  Ortholog locus
                  <input
                    value={form.orthologLocus}
                    onChange={(event) => updateForm("orthologLocus", event.target.value)}
                    className="workbench-input"
                    placeholder="Leave blank to search within the selected profile"
                  />
                </label>
                <label className="grid gap-2 font-medium">
                  Ortholog gene name (optional)
                  <input
                    value={form.orthologName}
                    onChange={(event) => updateForm("orthologName", event.target.value)}
                    className="workbench-input"
                    placeholder="octT"
                  />
                </label>
              </div>
            ) : null}

            {isCustomProfile ? (
              <details className="workbench-muted-bg rounded-xl border workbench-border p-4 text-sm">
                <summary className="cursor-pointer font-bold">Advanced custom organism terms</summary>
                <div className="mt-4 grid gap-4">
                  <label className="grid gap-2">
                    Locus regex
                    <input
                      value={form.locusRegex}
                      onChange={(event) => updateForm("locusRegex", event.target.value)}
                      className="workbench-input"
                      placeholder="^CUS_\\d+$"
                    />
                  </label>
                  <label className="grid gap-2">
                    Search terms, one per line
                    <textarea
                      value={form.searchTerms}
                      onChange={(event) => updateForm("searchTerms", event.target.value)}
                      className="workbench-input min-h-24"
                    />
                  </label>
                  <label className="grid gap-2">
                    Target organism patterns, one per line
                    <textarea
                      value={form.targetPatterns}
                      onChange={(event) => updateForm("targetPatterns", event.target.value)}
                      className="workbench-input min-h-24"
                    />
                  </label>
                  <label className="grid gap-2">
                    Off-target patterns, one per line
                    <textarea
                      value={form.offTargetPatterns}
                      onChange={(event) => updateForm("offTargetPatterns", event.target.value)}
                      className="workbench-input min-h-24"
                    />
                  </label>
                  <label className="grid gap-2">
                    Excluded species patterns, one per line
                    <textarea
                      value={form.excludedSpeciesPatterns}
                      onChange={(event) => updateForm("excludedSpeciesPatterns", event.target.value)}
                      className="workbench-input min-h-24"
                    />
                  </label>
                </div>
              </details>
            ) : null}

            {statusMessage ? (
              <p className="workbench-amber-bg rounded-xl border workbench-border p-4 text-sm text-[#5f4b2e]">
                {statusMessage}
              </p>
            ) : null}

            <button
              type="submit"
              disabled={!canSubmit}
              suppressHydrationWarning
              className="workbench-button workbench-button-primary min-h-11 px-5 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isSubmitting ? "Submitting..." : "Queue annotation job"}
            </button>
          </form>
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
                <p className="workbench-amber-bg rounded-xl border workbench-border p-4 text-sm text-[#5f4b2e]">
                  {statusMessage}
                </p>
              ) : null}
            </div>
          )}
        </section>

        <section className="workbench-card p-6">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h2 className="workbench-foreground text-2xl font-bold tracking-[-0.03em]">Job queue</h2>
              <p className="workbench-muted w-full md:w-35 mt-2 text-sm">
                {queue.running || 0} running · {queue.queued || 0} queued ·{" "}
                {queue.completed || 0} completed · {queue.failed || 0} failed
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
                disabled={(queue.completed || 0) + (queue.failed || 0) === 0}
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
              visibleJobs.map((job) => <JobTile key={job.id} job={job} />)
            ) : (
              <div className="workbench-muted rounded-2xl border border-dashed workbench-border p-8 text-center">
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
