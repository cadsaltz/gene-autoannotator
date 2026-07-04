import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

import {
  formatFleetCapacityLabel,
  formatWorkersConnectedLabel,
} from "../lib/healthFormat.js";

const projectRoot = process.cwd();

async function readProjectFile(relativePath) {
  return readFile(path.join(projectRoot, relativePath), "utf8");
}

test("fleet dashboard formats worker count and slot fraction from health data", () => {
  const workers = {
    connected: 2,
    used_slots: 1,
    total_slots: 3,
    states: { ready: 2, provisioning: 0, draining: 0, offline: 0 },
  };

  assert.equal(formatWorkersConnectedLabel(workers), "2 workers");
  assert.equal(formatFleetCapacityLabel(workers), "1/3 slots");
});

test("fleet route renders the dashboard in the app shell", async () => {
  const route = await readProjectFile("app/fleet/page.js");

  assert.match(route, /import AppShell from "\.\.\/\.\.\/components\/AppShell";/);
  assert.match(route, /import FleetDashboard from "\.\.\/\.\.\/components\/FleetDashboard";/);
  assert.match(route, /<AppShell>\s*<FleetDashboard \/>\s*<\/AppShell>/s);
});

test("fleet dashboard polls health and worker endpoints every 12 seconds", async () => {
  const dashboard = await readProjectFile("components/FleetDashboard.js");

  assert.match(dashboard, /"use client";/);
  assert.match(
    dashboard,
    /import \{ getAnnotationHealth, getHealth, getWorkers \} from "\.\.\/lib\/api";/,
  );
  assert.match(dashboard, /window\.setInterval\(refreshFleet, 12000\)/);
  assert.match(dashboard, /formatWorkersConnectedLabel\(workerSummary\)/);
  assert.match(dashboard, /formatFleetCapacityLabel\(workerSummary\)/);
  assert.match(dashboard, /formatWorkerResourceDetail\(worker\)/);
  assert.match(dashboard, /formatWorkerDedicatedMemory\(worker\)/);
  assert.match(dashboard, /Last heartbeat \{formatHeartbeatAge\(worker\.last_heartbeat_at\)\}/);
});

test("job workspace imports shared health formatters", async () => {
  const workspace = await readProjectFile("components/JobWorkspace.js");

  assert.match(
    workspace,
    /import \{ formatFleetStatusStrip \} from "\.\.\/lib\/healthFormat";/,
  );
  assert.match(workspace, /formatFleetStatusStrip\(health, queue\)/);
  assert.match(workspace, /href="\/fleet"/);
  assert.doesNotMatch(workspace, /function formatBytes\(/);
  assert.doesNotMatch(workspace, /function formatResourceDetail\(/);
});
