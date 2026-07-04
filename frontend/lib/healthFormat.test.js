import assert from "node:assert/strict";
import test from "node:test";

import {
  buildJobsHealthDisplay,
  collectFleetHealthIssues,
  formatFleetCapacityDetail,
  formatFleetCapacityLabel,
  formatHeartbeatAge,
  formatQueueDetail,
  formatWorkerDedicatedMemory,
  formatWorkerResourceDetail,
  formatWorkerSlotsLabel,
  formatWorkersConnectedDetail,
  formatWorkersConnectedLabel,
  getAvailableSlots,
} from "./healthFormat.js";

test("formatWorkersConnectedLabel pluralizes worker count", () => {
  assert.equal(formatWorkersConnectedLabel({ connected: 2 }), "2 workers");
  assert.equal(formatWorkersConnectedLabel({ connected: 1 }), "1 worker");
  assert.equal(formatWorkersConnectedLabel(null), "0 workers");
});

test("formatWorkersConnectedDetail summarizes worker states", () => {
  assert.equal(
    formatWorkersConnectedDetail({
      connected: 2,
      states: { ready: 2, provisioning: 0, draining: 0, offline: 1 },
    }),
    "2 ready · 1 offline",
  );
});

test("formatFleetCapacityLabel renders available slots", () => {
  assert.equal(
    formatFleetCapacityLabel({ available_slots: 2, total_slots: 3, used_slots: 1 }),
    "2 of 3 slots available",
  );
  assert.equal(
    formatFleetCapacityLabel({ used_slots: 0, total_slots: 1 }),
    "1 of 1 slot available",
  );
});

test("getAvailableSlots falls back to total minus used", () => {
  assert.equal(getAvailableSlots({ used_slots: 1, total_slots: 4 }), 3);
  assert.equal(getAvailableSlots(null), 0);
});

test("formatFleetCapacityDetail explains in-use and open slots", () => {
  assert.equal(
    formatFleetCapacityDetail({ available_slots: 1, total_slots: 2, used_slots: 1 }),
    "1 in use · 1 open for new jobs",
  );
});

test("formatWorkerSlotsLabel prefers heartbeat free slots", () => {
  assert.equal(
    formatWorkerSlotsLabel({ free_slots: 1, max_slots: 2, active_jobs: 1 }),
    "1 of 2 slots available",
  );
});

test("collectFleetHealthIssues reports coordinator outage first", () => {
  const issues = collectFleetHealthIssues(
    { status: "offline", resources: { message: "connection refused" } },
    { status: "ok" },
  );
  assert.deepEqual(issues, [{ label: "Coordinator", message: "connection refused" }]);
});

test("collectFleetHealthIssues reports missing workers and storage problems", () => {
  const issues = collectFleetHealthIssues(
    {
      status: "ok",
      stores: {
        annotations: { status: "unavailable", message: "MONGO_URI is not configured" },
        jobs: { status: "ok" },
      },
      workers: { connected: 0, total_slots: 0, used_slots: 0, available_slots: 0 },
    },
    { status: "unavailable", message: "Mongo ping failed" },
  );

  assert.equal(issues.length, 3);
  assert.equal(issues[0].label, "MongoDB reads");
  assert.equal(issues[1].label, "MongoDB writes");
  assert.equal(issues[2].label, "Workers");
});

test("buildJobsHealthDisplay shows healthy confirmation and slot count", () => {
  const display = buildJobsHealthDisplay(
    {
      status: "ok",
      stores: { annotations: { status: "ok" }, jobs: { status: "ok" } },
      workers: { connected: 1, available_slots: 2, total_slots: 2, used_slots: 0 },
    },
    { status: "ok" },
  );

  assert.equal(display.tone, "ok");
  assert.equal(display.title, "All systems operational");
  assert.equal(display.message, "2 annotation slots available");
});

test("buildJobsHealthDisplay surfaces the primary issue when unhealthy", () => {
  const display = buildJobsHealthDisplay(
    {
      status: "ok",
      stores: { annotations: { status: "ok" }, jobs: { status: "ok" } },
      workers: { connected: 0, total_slots: 0, used_slots: 0, available_slots: 0 },
    },
    { status: "ok" },
  );

  assert.equal(display.tone, "warn");
  assert.equal(display.title, "Workers");
  assert.equal(display.message, "No workers connected — jobs cannot run");
});

test("formatQueueDetail renders queue lifecycle counts", () => {
  assert.equal(
    formatQueueDetail({ queued: 4, running: 1, completed: 10, failed: 2 }),
    "4 queued · 1 running · 10 completed · 2 failed",
  );
});

test("formatWorkerResourceDetail uses heartbeat resource fields", () => {
  const detail = formatWorkerResourceDetail({
    cpu_percent: 42.4,
    memory_available_bytes: 8 * 1024 ** 3,
    total_memory_bytes: 16 * 1024 ** 3,
    dedicated_memory_bytes: 12 * 1024 ** 3,
  });

  assert.match(detail, /CPU 42%/);
  assert.match(detail, /8\.0 GiB available \/ 16\.0 GiB total/);
});

test("formatWorkerDedicatedMemory renders dedicated and total memory in GB", () => {
  assert.equal(
    formatWorkerDedicatedMemory({
      dedicated_memory_bytes: 12 * 1024 ** 3,
      total_memory_bytes: 16 * 1024 ** 3,
    }),
    "12.0 GB / 16.0 GB",
  );
});

test("formatHeartbeatAge renders compact elapsed durations", () => {
  const now = Date.parse("2026-07-04T12:00:30.000Z");
  assert.equal(formatHeartbeatAge("2026-07-04T12:00:00.000Z", now), "30s ago");
});
