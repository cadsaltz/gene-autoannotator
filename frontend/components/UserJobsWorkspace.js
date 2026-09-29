"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import BatchJobForm from "./BatchJobForm";
import QueuePlaceholder from "./QueuePlaceholder";
import SingleJobForm, { queueSingleJob, useJobForm } from "./SingleJobForm";
import { cancelJob, getProfiles, getQueueStatus, listJobs } from "../lib/api";
import { formatJobStepLabel } from "../lib/jobProgress";
import { getAnnotationQuery, getJobDisplayName, isCancellable } from "../lib/jobQueue";
import { describeSubmitError, formatUsage } from "../lib/queueStatus";

const stepLabels = {
  queued: "Waiting in queue",
  running: "Annotator running",
  saving_result: "Saving result",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
};

const statusBadgeClasses = {
  queued: "bg-[#eee6d9] text-[#5a5248]",
  running: "bg-[#dbe8df] text-[#2d4a38]",
  completed: "bg-[#dde6f0] text-[#2f4a66]",
  failed: "bg-[#f3d9dc] text-[#7a3a41]",
  cancelled: "bg-[#e8e3db] text-[#5a5248]",
};

function formatSubmittedAt(value) {
  const parsed = value ? Date.parse(value) : Number.NaN;
  return Number.isNaN(parsed) ? "—" : new Date(parsed).toLocaleString();
}

function StatusCell({ job }) {
  const detail =
    job.status === "queued" && job.queue_position
      ? `#${job.queue_position} in line`
      : job.status === "running"
        ? formatJobStepLabel(job, stepLabels)
        : null;

  return (
    <div className="grid gap-1">
      <span
        className={`w-fit rounded-full px-2 py-0.5 text-xs font-bold uppercase tracking-wide ${
          statusBadgeClasses[job.status] || statusBadgeClasses.queued
        }`}
      >
        {job.status}
      </span>
      {detail ? <span className="workbench-muted text-xs">{detail}</span> : null}
      {job.status === "failed" && job.error ? (
        <span className="workbench-red text-xs">{job.error}</span>
      ) : null}
    </div>
  );
}

function UsagePanel({ queueStatus }) {
  return (
    <div className="workbench-card p-6">
      <p className="workbench-kicker">Your usage</p>
      {queueStatus ? (
        <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-3">
          <div className="border-t workbench-border pt-2">
            <dt className="workbench-muted text-xs font-bold uppercase tracking-[0.1em]">Active jobs</dt>
            <dd className="workbench-foreground mt-1 font-semibold">
              {formatUsage(queueStatus.your_active, queueStatus.your_active_limit)}
            </dd>
          </div>
          <div className="border-t workbench-border pt-2">
            <dt className="workbench-muted text-xs font-bold uppercase tracking-[0.1em]">Last 24 hours</dt>
            <dd className="workbench-foreground mt-1 font-semibold">
              {formatUsage(queueStatus.your_today, queueStatus.your_daily_limit)}
            </dd>
          </div>
          <div className="border-t workbench-border pt-2">
            <dt className="workbench-muted text-xs font-bold uppercase tracking-[0.1em]">Batch size</dt>
            <dd className="workbench-foreground mt-1 font-semibold">
              Up to {queueStatus.batch_limit} genes
            </dd>
          </div>
        </dl>
      ) : (
        <p className="workbench-muted mt-2 text-sm">Loading your limits…</p>
      )}
    </div>
  );
}

export default function UserJobsWorkspace() {
  const [queueStatus, setQueueStatus] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [profiles, setProfiles] = useState([]);
  const [loadError, setLoadError] = useState("");
  const [statusMessage, setStatusMessage] = useState("");
  const [jobsMessage, setJobsMessage] = useState("");
  const [submitMode, setSubmitMode] = useState("single");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [cancellingId, setCancellingId] = useState(null);
  const { form, updateForm, selectedProfile, isCustomProfile } = useJobForm(profiles);

  const accepting = queueStatus?.accepting === true;
  const canSubmit = accepting && !isSubmitting;

  async function refresh() {
    const [statusResult, jobsResult] = await Promise.allSettled([
      getQueueStatus(),
      listJobs("newest"),
    ]);
    if (statusResult.status === "fulfilled") {
      setQueueStatus(statusResult.value);
    }
    if (jobsResult.status === "fulfilled") {
      setJobs(jobsResult.value.jobs || []);
    }
    const failure = [statusResult, jobsResult].find((result) => result.status === "rejected");
    setLoadError(failure ? failure.reason?.message || "Could not load your jobs." : "");
  }

  useEffect(() => {
    async function loadInitialData() {
      try {
        const payload = await getProfiles();
        setProfiles(payload.profiles || []);
      } catch (error) {
        setStatusMessage(error.message);
      }
      await refresh();
    }

    loadInitialData();
    const timer = window.setInterval(refresh, 15000);
    return () => {
      window.clearInterval(timer);
    };
  }, []);

  async function handleSubmit(event) {
    event.preventDefault();
    setStatusMessage("");
    setIsSubmitting(true);

    try {
      setStatusMessage(await queueSingleJob(form));
      await refresh();
    } catch (error) {
      setStatusMessage(describeSubmitError(error));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleCancel(job) {
    const confirmed = window.confirm(`Cancel the job for ${getJobDisplayName(job)}?`);
    if (!confirmed) {
      return;
    }

    setCancellingId(job.id);
    setJobsMessage("");
    try {
      await cancelJob(job.id);
      await refresh();
      setJobsMessage(`Cancelled the job for ${getJobDisplayName(job)}.`);
    } catch (error) {
      setJobsMessage(error.message);
      await refresh();
    } finally {
      setCancellingId(null);
    }
  }

  return (
    <div className="grid gap-5">
      <section className="workbench-card p-6">
        <p className="workbench-kicker">Jobs</p>
        <h1 className="workbench-foreground mt-2 text-3xl font-bold tracking-[-0.04em]">
          Submit and track your jobs
        </h1>
        <p className="workbench-muted mt-3 max-w-2xl text-sm leading-6">
          Choose a profile, enter a gene, and add it to the shared queue. Jobs run in order and a
          real annotation can take hours; this page refreshes on its own.
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          <button
            type="button"
            onClick={refresh}
            className="workbench-button workbench-button-secondary"
          >
            Refresh
          </button>
        </div>
        {loadError ? <p className="workbench-red mt-4 text-sm">{loadError}</p> : null}
      </section>

      <div className="grid gap-5 md:grid-cols-2">
        <QueuePlaceholder status={queueStatus} />
        <UsagePanel queueStatus={queueStatus} />
      </div>

      <div className="grid items-start gap-5 lg:grid-cols-[0.95fr_1.05fr]">
        <section className="workbench-card p-6">
          <h2 className="text-2xl font-bold tracking-[-0.03em]">New annotation job</h2>
          <p className="workbench-muted mt-3 text-sm leading-6">
            Provide a gene name, locus, or both, or switch to batch mode to queue a list.
          </p>

          {queueStatus && !accepting ? (
            <p className="workbench-amber-bg mt-4 rounded-xl border workbench-border p-4 text-sm text-[#5f4b2e]">
              Submissions are paused because the shared queue is full. Your existing jobs keep
              running; please try again later.
            </p>
          ) : null}

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
            <SingleJobForm
              form={form}
              updateForm={updateForm}
              profiles={profiles}
              selectedProfile={selectedProfile}
              isCustomProfile={isCustomProfile}
              canSubmit={canSubmit}
              isSubmitting={isSubmitting}
              statusMessage={statusMessage}
              onSubmit={handleSubmit}
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
                onBatchSubmitted={() => {
                  refresh();
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
          <h2 className="workbench-foreground text-2xl font-bold tracking-[-0.03em]">My jobs</h2>
          <p className="workbench-muted mt-2 text-sm">
            Only jobs you submitted are listed here.
          </p>

          {jobsMessage ? (
            <p className="workbench-amber-bg mt-4 rounded-xl border workbench-border p-4 text-sm text-[#5f4b2e]">
              {jobsMessage}
            </p>
          ) : null}

          {jobs.length > 0 ? (
            <div className="mt-6 overflow-x-auto rounded-xl border workbench-border">
              <table className="min-w-full text-left text-sm">
                <thead className="workbench-muted-bg workbench-muted text-xs font-bold uppercase tracking-[0.08em]">
                  <tr>
                    <th className="px-3 py-2">Gene / locus</th>
                    <th className="px-3 py-2">Status</th>
                    <th className="px-3 py-2">Submitted</th>
                    <th className="px-3 py-2">
                      <span className="sr-only">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {jobs.map((job) => {
                    const request = job.request || {};
                    return (
                      <tr key={job.id} className="border-t workbench-border">
                        <td className="px-3 py-2 align-top">
                          <p className="workbench-foreground font-semibold">{getJobDisplayName(job)}</p>
                          <p className="workbench-muted font-mono text-xs">
                            {request.profile || request.organism || "default profile"}
                            {request.locus ? ` · ${request.locus}` : ""}
                          </p>
                        </td>
                        <td className="px-3 py-2 align-top">
                          <StatusCell job={job} />
                        </td>
                        <td className="workbench-muted px-3 py-2 align-top text-xs">
                          {formatSubmittedAt(job.created_at)}
                        </td>
                        <td className="px-3 py-2 align-top text-right">
                          {job.status === "completed" && job.result_available ? (
                            <Link
                              href={`/annotations?query=${encodeURIComponent(getAnnotationQuery(job))}`}
                              className="workbench-green text-sm font-bold hover:text-[#111a16]"
                            >
                              View annotation
                            </Link>
                          ) : null}
                          {isCancellable(job) ? (
                            <button
                              type="button"
                              onClick={() => handleCancel(job)}
                              disabled={cancellingId === job.id}
                              className="workbench-button workbench-button-secondary disabled:cursor-not-allowed disabled:opacity-50"
                            >
                              Cancel
                            </button>
                          ) : null}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="workbench-muted mt-6 rounded-2xl border border-dashed workbench-border p-8 text-center">
              You have not submitted any jobs yet.
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
