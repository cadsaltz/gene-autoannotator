"use client";

import { useEffect, useState } from "react";

import { getAnnotationHealth, getHealth, getWorkers } from "../lib/api";
import {
  formatFleetCapacityDetail,
  formatFleetCapacityLabel,
  formatHeartbeatAge,
  formatQueueDetail,
  formatShortWorkerId,
  formatWorkerDedicatedMemory,
  formatWorkerResourceDetail,
  formatWorkerSlotsLabel,
  formatWorkersConnectedDetail,
  formatWorkersConnectedLabel,
  getAvailableSlots,
} from "../lib/healthFormat";

function HealthBadge({ label, status, detail }) {
  const ok = status === "ok";
  return (
    <div
      className={`workbench-surface-bg min-h-32 rounded-2xl border workbench-border p-4 ${
        ok ? "health-status-ok" : "health-status-warn"
      }`}
    >
      <p className="workbench-muted text-sm font-semibold">{label}</p>
      <p className="workbench-foreground mt-2 text-base font-bold">
        {ok ? "Connected" : status || "Unavailable"}
      </p>
      {detail ? <p className="workbench-muted mt-2 text-xs leading-5">{detail}</p> : null}
    </div>
  );
}

function MetricBadge({ label, value, detail, ok = true }) {
  return (
    <div
      className={`workbench-surface-bg min-h-32 rounded-2xl border workbench-border p-4 ${
        ok ? "health-status-ok" : "health-status-warn"
      }`}
    >
      <p className="workbench-muted text-sm font-semibold">{label}</p>
      <p className="workbench-foreground mt-2 text-base font-bold">{value}</p>
      {detail ? <p className="workbench-muted mt-2 text-xs leading-5">{detail}</p> : null}
    </div>
  );
}

function workerStateTone(state) {
  if (state === "ready") return "health-status-ok";
  if (state === "offline") return "health-status-warn";
  return "workbench-muted-bg";
}

function WorkerCard({ worker }) {
  const stateClass = workerStateTone(worker.state);

  return (
    <article className={`rounded-2xl border workbench-border p-4 ${stateClass}`}>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="workbench-foreground text-lg font-bold tracking-[-0.02em]">
            {worker.worker_name || "Unknown worker"}
          </p>
          <p className="workbench-muted mt-1 text-sm">
            {worker.hostname || "unknown host"} · {formatShortWorkerId(worker.id)}
          </p>
        </div>
        <div className="flex flex-col items-start gap-1 sm:items-end">
          <span className="rounded-full border workbench-border bg-white/60 px-3 py-1 text-xs font-bold uppercase tracking-wide text-[#3f4b43]">
            {worker.state || "unknown"}
          </span>
          <p className="workbench-muted text-xs">
            Last heartbeat {formatHeartbeatAge(worker.last_heartbeat_at)}
          </p>
        </div>
      </div>

      <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
        <div className="border-t workbench-border pt-2">
          <dt className="workbench-muted text-xs font-bold uppercase tracking-[0.1em]">Slots</dt>
          <dd className="mt-1 text-[#3d463f]">{formatWorkerSlotsLabel(worker)}</dd>
        </div>
        <div className="border-t workbench-border pt-2">
          <dt className="workbench-muted text-xs font-bold uppercase tracking-[0.1em]">Agent</dt>
          <dd className="mt-1 text-[#3d463f]">{worker.agent_version || "unknown"}</dd>
        </div>
        <div className="border-t workbench-border pt-2 sm:col-span-2">
          <dt className="workbench-muted text-xs font-bold uppercase tracking-[0.1em]">Resources</dt>
          <dd className="mt-1 text-[#3d463f]">{formatWorkerResourceDetail(worker)}</dd>
        </div>
        <div className="border-t workbench-border pt-2 sm:col-span-2">
          <dt className="workbench-muted text-xs font-bold uppercase tracking-[0.1em]">
            Dedicated memory
          </dt>
          <dd className="mt-1 text-[#3d463f]">{formatWorkerDedicatedMemory(worker)}</dd>
        </div>
      </dl>
    </article>
  );
}

export default function FleetDashboard() {
  const [health, setHealth] = useState(null);
  const [annotationHealth, setAnnotationHealth] = useState(null);
  const [workers, setWorkers] = useState([]);

  async function refreshFleet() {
    try {
      setHealth(await getHealth());
    } catch (error) {
      setHealth({
        status: "offline",
        stores: {},
        queue: {},
        workers: {},
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

    try {
      const payload = await getWorkers();
      setWorkers(payload.workers || []);
    } catch {
      setWorkers([]);
    }
  }

  useEffect(() => {
    refreshFleet();
    const timer = window.setInterval(refreshFleet, 12000);
    return () => window.clearInterval(timer);
  }, []);

  const workerSummary = health?.workers;

  return (
    <div className="grid gap-5">
      <section className="workbench-card p-6">
        <p className="workbench-kicker">Fleet</p>
        <h1 className="workbench-foreground mt-2 text-3xl font-bold tracking-[-0.04em]">
          Fleet &amp; health
        </h1>
        <p className="workbench-muted mt-3 max-w-2xl text-sm leading-6">
          Monitor coordinator connectivity, storage, queue pressure, and registered annotation
          workers. This page refreshes every 12 seconds.
        </p>
        <div className="mt-6">
          <button
            type="button"
            onClick={refreshFleet}
            className="workbench-button workbench-button-secondary"
          >
            Refresh
          </button>
        </div>
      </section>

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <HealthBadge
          label="Frontend → Coordinator"
          status={health?.status}
          detail={health?.status === "ok" ? "Coordinator API reachable" : health?.resources?.message}
        />
        <HealthBadge
          label="Frontend → MongoDB reads"
          status={annotationHealth?.status}
          detail={
            annotationHealth?.status === "ok"
              ? "Next server can reach MongoDB"
              : annotationHealth?.message
          }
        />
        <HealthBadge
          label="Coordinator → MongoDB writes"
          status={health?.stores?.annotations?.status}
          detail={health?.stores?.annotations?.message || health?.stores?.annotations?.database}
        />
        <HealthBadge
          label="Job store SQLite"
          status={health?.stores?.jobs?.status}
          detail={health?.stores?.jobs?.path}
        />
        <MetricBadge
          label="Queue"
          value="Job counts"
          detail={formatQueueDetail(health?.queue)}
        />
        <MetricBadge
          label="Workers connected"
          value={formatWorkersConnectedLabel(workerSummary)}
          detail={formatWorkersConnectedDetail(workerSummary)}
          ok={(workerSummary?.connected ?? 0) > 0}
        />
        <MetricBadge
          label="Fleet capacity"
          value={formatFleetCapacityLabel(workerSummary)}
          detail={formatFleetCapacityDetail(workerSummary)}
          ok={getAvailableSlots(workerSummary) > 0}
        />
      </section>

      <section className="workbench-card p-6">
        <h2 className="workbench-foreground text-2xl font-bold tracking-[-0.03em]">Workers</h2>
        <p className="workbench-muted mt-2 text-sm">
          {workers.length > 0
            ? `${workers.length} registered worker${workers.length === 1 ? "" : "s"}`
            : "No workers registered yet."}
        </p>

        <div className="mt-6 grid gap-4 lg:grid-cols-2">
          {workers.length > 0 ? (
            workers.map((worker) => <WorkerCard key={worker.id} worker={worker} />)
          ) : (
            <div className="workbench-muted rounded-2xl border border-dashed workbench-border p-8 text-center lg:col-span-2">
              Start a worker process to see fleet members here.
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
