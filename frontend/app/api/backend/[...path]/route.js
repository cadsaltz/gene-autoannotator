import { copyProxyHeaders, fetchBackendResponse } from "../../../../lib/backendProxy";

const DEFAULT_BACKEND_API_BASE_URL = "http://127.0.0.1:8000";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

// Browser code calls this same-origin proxy instead of FastAPI directly. That
// keeps local/server deployments consistent and avoids exposing a public backend
// URL to client bundles.
function getBackendApiBaseUrl() {
  return process.env.BACKEND_API_BASE_URL || DEFAULT_BACKEND_API_BASE_URL;
}

async function buildBackendUrl(request, context) {
  const params = await context.params;
  const path = params.path || [];
  const backendUrl = new URL(path.map(encodeURIComponent).join("/"), `${getBackendApiBaseUrl()}/`);
  backendUrl.search = new URL(request.url).search;
  return backendUrl;
}

async function proxyRequest(request, context) {
  const backendUrl = await buildBackendUrl(request, context);
  const headers = copyProxyHeaders(request.headers);
  headers.delete("host");

  const init = {
    method: request.method,
    headers,
    redirect: "manual",
  };

  if (request.method !== "GET" && request.method !== "HEAD") {
    init.body = await request.arrayBuffer();
  }

  return fetchBackendResponse(backendUrl, init);
}

export const GET = proxyRequest;
export const POST = proxyRequest;
export const PUT = proxyRequest;
export const PATCH = proxyRequest;
export const DELETE = proxyRequest;
export const OPTIONS = proxyRequest;

