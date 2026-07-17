const COMPACT_JOB_COUNT = 2;

// Keep the queue readable on the jobs page while preserving access to the full
// backend history via an explicit expand action.
export function getVisibleJobs(jobs, expanded) {
  const normalizedJobs = Array.isArray(jobs) ? jobs : [];
  return expanded ? normalizedJobs : normalizedJobs.slice(0, COMPACT_JOB_COUNT);
}

export function getHiddenJobCount(jobs) {
  const normalizedJobs = Array.isArray(jobs) ? jobs : [];
  return Math.max(0, normalizedJobs.length - COMPACT_JOB_COUNT);
}

export function shouldShowRunningSpinner(job) {
  return job?.status === "running";
}

export function filterJobsByBatch(jobs, batchId) {
  const normalizedJobs = Array.isArray(jobs) ? jobs : [];
  if (!batchId) {
    return normalizedJobs;
  }
  return normalizedJobs.filter((job) => job.batch_id === batchId);
}

export function getJobDisplayName(job) {
  const request = job?.request || {};
  return (
    request.name ||
    request.target_preflight?.resolved_name ||
    request.locus ||
    "Unknown locus"
  );
}
