const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";
const BROWSER_API_BASE_URL = "/api/backend";
const ANNOTATION_API_BASE_URL = "/api/annotations";

function getBrowserApiBaseUrl() {
  if (typeof window === "undefined") {
    return null;
  }
  return BROWSER_API_BASE_URL;
}

export function getApiBaseUrl() {
  // Server components can call FastAPI directly, but browser components always
  // use the Next proxy so CORS and deployment topology stay centralized.
  const browserApiBaseUrl = getBrowserApiBaseUrl();

  if (browserApiBaseUrl) {
    return browserApiBaseUrl;
  }

  return process.env.BACKEND_API_BASE_URL || process.env.COORDINATOR_API_BASE_URL || DEFAULT_API_BASE_URL;
}

export function getAnnotationApiBaseUrl() {
  return ANNOTATION_API_BASE_URL;
}

function formatErrorDetail(detail, fallback) {
  if (!detail) {
    return fallback;
  }
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    const messages = detail.map((entry) => formatErrorDetail(entry, "")).filter(Boolean);
    return messages.length > 0 ? messages.join(" ") : fallback;
  }
  if (typeof detail === "object") {
    if (detail.msg) {
      return formatErrorDetail(detail.msg, fallback);
    }
    if (detail.message) {
      return formatErrorDetail(detail.message, fallback);
    }
    if (detail.detail) {
      return formatErrorDetail(detail.detail, fallback);
    }
    return JSON.stringify(detail);
  }
  return String(detail);
}

async function apiFetchFrom(baseUrl, path, options = {}) {
  const response = await fetch(`${baseUrl}${path}`, {
    cache: "no-store",
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });

  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = formatErrorDetail(payload?.detail, `Backend returned HTTP ${response.status}`);
    throw new Error(detail);
  }
  return payload;
}

async function apiFetch(path, options = {}) {
  return apiFetchFrom(getApiBaseUrl(), path, options);
}

async function annotationApiFetch(path, options = {}) {
  return apiFetchFrom(getAnnotationApiBaseUrl(), path, options);
}

export async function getHealth() {
  return apiFetch("/health");
}

export async function getWorkers() {
  return apiFetch("/workers");
}

export async function getProfiles() {
  return apiFetch("/profiles");
}

export async function getProfile(profileId) {
  return apiFetch(`/profiles/${encodeURIComponent(profileId)}`);
}

export async function createProfile(payload) {
  return apiFetch("/profiles", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateProfile(profileId, payload) {
  return apiFetch(`/profiles/${encodeURIComponent(profileId)}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function deleteProfile(profileId) {
  return apiFetch(`/profiles/${encodeURIComponent(profileId)}`, {
    method: "DELETE",
  });
}

export async function validateJob(payload) {
  return apiFetch("/validate", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function generateRegexFromExamples(payload) {
  return apiFetch("/regex/from-examples", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function generateRegexFromDescription(payload) {
  return apiFetch("/regex/from-description", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function createJob(payload) {
  return apiFetch("/jobs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function listJobs(order = "queue") {
  return apiFetch(`/jobs?order=${encodeURIComponent(order)}`);
}

export async function clearFinishedJobHistory() {
  return apiFetch("/jobs/history", {
    method: "DELETE",
  });
}

export async function validateBatch(payload) {
  return apiFetch("/batches/validate", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function createBatch(payload) {
  return apiFetch("/batches", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getBatch(batchId) {
  return apiFetch(`/batches/${encodeURIComponent(batchId)}`);
}

export async function searchAnnotations(query) {
  return annotationApiFetch(`/search?query=${encodeURIComponent(query)}`);
}

export async function getAnnotation(annotationId) {
  return annotationApiFetch(`/${encodeURIComponent(annotationId)}`);
}

export async function getAnnotationVersions(annotationId) {
  return annotationApiFetch(`/${encodeURIComponent(annotationId)}/versions`);
}

export async function getAnnotationHealth() {
  const response = await fetch(`${getAnnotationApiBaseUrl()}/health`, {
    cache: "no-store",
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok && !payload) {
    throw new Error(`Annotation health returned HTTP ${response.status}`);
  }
  return payload;
}
