// Pure helpers for job tile progress display. Kept free of React/framer-motion
// so they can be unit tested directly with node:test.

function isOrthologPhase(job) {
  return (
    job.pass_name === "ortholog" ||
    (typeof job.progress_phase === "string" && job.progress_phase.startsWith("ortholog_"))
  );
}

// Bar is split target/ortholog when an ortholog fallback pass is in play:
// target owns the full bar until an ortholog progress event appears, then
// target holds 0-50% and ortholog owns 50-100%. See design doc "Progress bar
// (ortholog-aware)".
export function progressPercent(job) {
  if (job.status === "completed" || job.status === "failed") {
    return 100;
  }

  const clampRunning = (value) => (job.status === "running" ? Math.min(value, 99) : value);
  const sectionsDone = job.sections_done || 0;
  const sectionsTotal = job.sections_total || 0;

  if (isOrthologPhase(job)) {
    if (!sectionsTotal) {
      return 50;
    }
    return Math.round(clampRunning(50 + 50 * (sectionsDone / sectionsTotal)));
  }

  if (sectionsTotal) {
    return Math.round(clampRunning(100 * (sectionsDone / sectionsTotal)));
  }

  if (job.progress_phase === "aggregating") {
    return Math.round(clampRunning(97));
  }

  // Coarse fallback for jobs without structured progress fields.
  if (job.current_step === "saving_result") return 85;
  if (job.status === "running") return 55;
  return 12;
}

// Prefer structured fields for a precise "<phase> · n/m sections (pass)"
// label; fall back to the legacy per-status label map for older jobs. The
// subtitle always reports the current pass's own n/m, not a combined total.
export function formatJobStepLabel(job, stepLabels) {
  if (job.progress_phase && job.sections_total) {
    const done = job.sections_done ?? 0;
    const passSuffix = job.pass_name ? ` (${job.pass_name})` : "";
    return `${job.progress_phase} · ${done}/${job.sections_total} sections${passSuffix}`;
  }

  return stepLabels[job.current_step] || stepLabels[job.status] || job.status;
}
