"use client";

import { useEffect, useState } from "react";

import { getQueueStatus } from "../../lib/api";
import { formatQueuedCount, formatUsage } from "../../lib/queueStatus";

const HEADING = "Your limits";
const SIGNED_OUT_COPY =
  "Sign in to see your current usage and the limits on your account. Unless the operator changes them, each account can have 20 active jobs, submit 50 jobs per 24 hours, and send batches of up to 25 genes.";

function describeQueueState(queueStatus) {
  if (queueStatus.accepting === true) return "submissions open";
  if (queueStatus.paused === true) return "submissions paused by the operator";
  return "queue full, try again later";
}

function Stat({ label, value }) {
  return (
    <div className="border-t workbench-border pt-2">
      <dt className="workbench-muted text-xs font-medium">{label}</dt>
      <dd className="workbench-foreground mt-1 font-semibold">{value}</dd>
    </div>
  );
}

export default function QueueLimits() {
  const [queueStatus, setQueueStatus] = useState(null);

  useEffect(() => {
    let cancelled = false;
    getQueueStatus()
      .then((data) => {
        if (!cancelled) setQueueStatus(data);
      })
      .catch(() => {
        if (!cancelled) setQueueStatus(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="workbench-card p-6" aria-live="polite">
      <h3 className="workbench-foreground text-lg font-semibold tracking-tight">{HEADING}</h3>
      {queueStatus ? (
        <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
          <Stat
            label="Active jobs"
            value={formatUsage(queueStatus.your_active, queueStatus.your_active_limit)}
          />
          <Stat
            label="Last 24 hours"
            value={formatUsage(queueStatus.your_today, queueStatus.your_daily_limit)}
          />
          <Stat label="Batch size" value={`Up to ${queueStatus.batch_limit} genes`} />
          <Stat
            label="Shared queue"
            value={`${formatQueuedCount(queueStatus.queued)} · ${describeQueueState(queueStatus)}`}
          />
        </dl>
      ) : (
        <p className="workbench-muted mt-2 text-sm leading-6">{SIGNED_OUT_COPY}</p>
      )}
    </div>
  );
}
