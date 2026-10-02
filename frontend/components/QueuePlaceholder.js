import { formatQueuedCount } from "../lib/queueStatus";

export default function QueuePlaceholder({ status }) {
  if (!status) {
    return (
      <div className="workbench-card p-6" role="status">
        <p className="workbench-kicker">Shared queue</p>
        <p className="workbench-muted mt-2 text-sm">Checking the queue…</p>
      </div>
    );
  }

  const accepting = status.accepting === true;

  return (
    <div
      className={`workbench-card p-6 ${accepting ? "health-status-ok" : "health-status-warn"}`}
      role="status"
    >
      <p className="workbench-kicker">Shared queue</p>
      <p className="workbench-foreground mt-2 text-3xl font-semibold tracking-tight">
        {formatQueuedCount(status.queued)}
      </p>
      <p className={`mt-2 text-sm font-semibold ${accepting ? "workbench-green" : "workbench-amber"}`}>
        {accepting ? "Submissions open" : "Submissions paused"}
      </p>
    </div>
  );
}
