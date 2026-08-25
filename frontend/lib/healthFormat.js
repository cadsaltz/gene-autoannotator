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

export function getAvailableSlots(workers) {
  if (!workers) {
    return 0;
  }

  if (workers.available_slots != null) {
    return workers.available_slots;
  }

  const total = workers.total_slots ?? 0;
  const used = workers.used_slots ?? 0;
  return Math.max(0, total - used);
}

export function formatFleetCapacityLabel(workers) {
  const available = getAvailableSlots(workers);
  const total = workers?.total_slots ?? 0;
  const slotWord = total === 1 ? "slot" : "slots";
  return `${available} of ${total} ${slotWord} available`;
}

export function formatFleetCapacityDetail(workers) {
  const used = workers?.used_slots ?? 0;
  const total = workers?.total_slots ?? 0;
  if (total === 0) {
    return "No worker capacity registered";
  }
  return `${used} in use · ${getAvailableSlots(workers)} open for new jobs`;
}

export function formatWorkerSlotsLabel(worker) {
  const available = worker?.free_slots ?? Math.max(0, (worker?.max_slots ?? 0) - (worker?.active_jobs ?? 0));
  const total = worker?.max_slots ?? 0;
  const slotWord = total === 1 ? "slot" : "slots";
  return `${available} of ${total} ${slotWord} available`;
}

export function collectFleetHealthIssues(health, annotationHealth) {
  const issues = [];

  if (!health || health.status !== "ok") {
    issues.push({
      label: "Backend",
      message: health?.resources?.message || "Backend API unreachable",
    });
    return issues;
  }

  if (!annotationHealth || annotationHealth.status !== "ok") {
    issues.push({
      label: "MongoDB reads",
      message: annotationHealth?.message || "Frontend cannot reach MongoDB",
    });
  }

  const annotationStore = health.stores?.annotations;
  if (annotationStore?.status !== "ok") {
    issues.push({
      label: "MongoDB writes",
      message: annotationStore?.message || "Backend cannot write annotations to MongoDB",
    });
  }

  const jobStore = health.stores?.jobs;
  if (jobStore?.status !== "ok") {
    issues.push({
      label: "Job store",
      message: jobStore?.message || "SQLite job store unavailable",
    });
  }

  const workers = health.workers;
  const connected = workers?.connected ?? 0;
  if (connected === 0) {
    issues.push({
      label: "Workers",
      message: "No workers connected — jobs cannot run",
    });
    return issues;
  }

  const totalSlots = workers?.total_slots ?? 0;
  const availableSlots = getAvailableSlots(workers);
  if (totalSlots === 0) {
    issues.push({
      label: "Capacity",
      message: "Workers are connected but have zero job slots",
    });
  } else if (availableSlots === 0) {
    issues.push({
      label: "Capacity",
      message: "All worker slots are busy",
    });
  }

  return issues;
}

export function buildJobsHealthDisplay(health, annotationHealth) {
  const issues = collectFleetHealthIssues(health, annotationHealth);
  if (issues.length > 0) {
    const [primary, ...rest] = issues;
    return {
      tone: "warn",
      title: primary.label,
      message: primary.message,
      extraCount: rest.length,
      issues,
    };
  }

  const available = getAvailableSlots(health?.workers);
  const slotLabel =
    available === 1 ? "1 annotation slot available" : `${available} annotation slots available`;

  return {
    tone: "ok",
    title: "All systems operational",
    message: slotLabel,
    extraCount: 0,
    issues: [],
  };
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
