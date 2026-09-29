export function formatQueuedCount(queued) {
  const count = Number.isFinite(queued) ? queued : 0;
  return `${count} job${count === 1 ? "" : "s"} queued`;
}

export function formatUsage(used, limit) {
  const count = Number.isFinite(used) ? used : 0;
  if (limit === null || limit === undefined) {
    return `${count} (no limit)`;
  }
  return `${count} / ${limit}`;
}

const QUOTA_FALLBACK_MESSAGES = {
  queue_full: "The queue is full right now. Please try again later.",
  active_limit: "You have reached your limit of active jobs. Wait for one to finish or cancel one.",
  daily_limit: "You have reached your submission limit for the last 24 hours.",
  batch_limit: "This batch is larger than your batch size limit.",
  rate_limited: "Too many requests. Please wait a moment and try again.",
};

const GENERIC_429 = "Too many submissions right now. Please try again later.";

export function describeSubmitError(error) {
  const message = error?.message || "";
  if (error?.status !== 429) {
    return message || "Something went wrong.";
  }
  if (message && !/^Backend returned HTTP \d+$/.test(message)) {
    return message;
  }
  return QUOTA_FALLBACK_MESSAGES[error.code] || GENERIC_429;
}
