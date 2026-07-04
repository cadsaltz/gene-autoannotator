export function formatBytes(bytes) {
  if (bytes == null || Number.isNaN(Number(bytes))) {
    return "unknown";
  }

  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let value = Number(bytes);
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}

export function formatResourceDetail(resources) {
  if (!resources || resources.status !== "ok") {
    return resources?.message;
  }

  const cpu = `${Math.round(resources.cpu_percent ?? 0)}%`;
  const used = formatBytes(resources.memory_used_bytes);
  const total = formatBytes(resources.memory_total_bytes);
  const available = formatBytes(resources.memory_available_bytes);
  const memoryPercent = Math.round(resources.memory_percent ?? 0);

  return `CPU ${cpu} · RAM ${used} / ${total} used (${memoryPercent}%) · ${available} available`;
}

export function formatWorkerResourceDetail(worker) {
  if (!worker) {
    return undefined;
  }

  const cpu = `${Math.round(worker.cpu_percent ?? 0)}%`;
  const available = formatBytes(worker.memory_available_bytes);
  const total = formatBytes(worker.total_memory_bytes);

  return `CPU ${cpu} · RAM ${available} available / ${total} total`;
}

export function formatWorkerDedicatedMemory(worker) {
  if (!worker) {
    return undefined;
  }

  const dedicatedGb = formatMemoryGb(worker.dedicated_memory_bytes);
  const totalGb = formatMemoryGb(worker.total_memory_bytes);
  return `${dedicatedGb} / ${totalGb}`;
}

export function formatWorkersConnectedLabel(workers) {
  const connected = workers?.connected ?? 0;
  return `${connected} worker${connected === 1 ? "" : "s"}`;
}

export function formatWorkersConnectedDetail(workers) {
  if (!workers) {
    return undefined;
  }

  const states = workers.states || {};
  const parts = [
    states.ready ? `${states.ready} ready` : null,
    states.provisioning ? `${states.provisioning} provisioning` : null,
    states.draining ? `${states.draining} draining` : null,
    states.offline ? `${states.offline} offline` : null,
  ].filter(Boolean);

  return parts.length > 0 ? parts.join(" · ") : undefined;
}

export function formatFleetCapacityLabel(workers) {
  const used = workers?.used_slots ?? 0;
  const total = workers?.total_slots ?? 0;
  return `${used}/${total} slots`;
}

export function formatQueueDetail(queue) {
  if (!queue) {
    return undefined;
  }

  return `${queue.queued ?? 0} queued · ${queue.running ?? 0} running · ${queue.completed ?? 0} completed · ${queue.failed ?? 0} failed`;
}

export function formatHeartbeatAge(isoTimestamp, now = Date.now()) {
  if (!isoTimestamp) {
    return "never";
  }

  const heartbeatMs = Date.parse(isoTimestamp);
  if (Number.isNaN(heartbeatMs)) {
    return "unknown";
  }

  const ageSeconds = Math.max(0, Math.round((now - heartbeatMs) / 1000));
  if (ageSeconds < 60) {
    return `${ageSeconds}s ago`;
  }

  const ageMinutes = Math.round(ageSeconds / 60);
  if (ageMinutes < 60) {
    return `${ageMinutes}m ago`;
  }

  const ageHours = Math.round(ageMinutes / 60);
  return `${ageHours}h ago`;
}

export function formatShortWorkerId(workerId) {
  if (!workerId) {
    return "unknown";
  }

  return workerId.length <= 8 ? workerId : workerId.slice(-8);
}

function formatMemoryGb(bytes) {
  if (bytes == null || Number.isNaN(Number(bytes))) {
    return "unknown GB";
  }

  return `${(Number(bytes) / 1024 ** 3).toFixed(1)} GB`;
}
