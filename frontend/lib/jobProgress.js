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
//
// Fetching / pre-extraction holds at FETCH_BASE% so the bar isn't empty while
// papers load; extraction then fills the remaining (100 - FETCH_BASE)%.
const FETCH_BASE = 5;

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
    // Extraction maps into the band after the fetch placeholder.
    return Math.round(
      clampRunning(FETCH_BASE + (100 - FETCH_BASE) * (sectionsDone / sectionsTotal)),
    );
  }

  if (job.progress_phase === "aggregating") {
    return Math.round(clampRunning(97));
  }

  // Fetching / running with no section totals yet — small placeholder.
  if (job.progress_phase === "fetching" || job.status === "running") {
    if (job.current_step === "saving_result") return 85;
    return FETCH_BASE;
  }
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
