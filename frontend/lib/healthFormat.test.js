import assert from "node:assert/strict";
import test from "node:test";

import {
  formatFleetCapacityLabel,
  formatFleetStatusStrip,
  formatHeartbeatAge,
  formatQueueDetail,
  formatWorkerDedicatedMemory,
  formatWorkerResourceDetail,
  formatWorkersConnectedDetail,
  formatWorkersConnectedLabel,
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

test("formatFleetCapacityLabel renders used and total slots", () => {
  assert.equal(formatFleetCapacityLabel({ used_slots: 1, total_slots: 3 }), "1/3 slots");
});

test("formatFleetStatusStrip renders compact coordinator, worker, and queue summary", () => {
  assert.equal(
    formatFleetStatusStrip(
      { status: "ok", workers: { connected: 2, used_slots: 1, total_slots: 4 } },
      { queued: 3, running: 1 },
    ),
    "Coordinator: up · 2 workers · 1/4 slots · 3 queued, 1 running",
  );
  assert.equal(
    formatFleetStatusStrip(null, null),
    "Coordinator: down · 0 workers · 0/0 slots · 0 queued, 0 running",
  );
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
