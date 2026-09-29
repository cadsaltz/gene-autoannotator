import { getApiBaseUrl } from "./api.js";
import { sanitizeNextPath } from "./authPaths.js";

const SESSION_COOKIE = "ga_session";

function cookieHeaderFrom(source) {
  if (!source) return "";
  if (typeof source === "string") return source;
  if (typeof source.headers?.get === "function") {
    return source.headers.get("cookie") || "";
  }
  if (typeof source.getAll === "function") {
    return source
      .getAll()
      .map((cookie) => `${cookie.name}=${cookie.value}`)
      .join("; ");
  }
  return "";
}

function hasSessionCookie(cookieHeader) {
  return cookieHeader
    .split(";")
    .some((part) => {
      const [name, ...rest] = part.trim().split("=");
      return name === SESSION_COOKIE && rest.join("=").length > 0;
    });
}

async function defaultCookieSource() {
  const { cookies } = await import("next/headers");
  return cookies();
}

/**
 * Server-side session lookup: forwards the caller's cookies to FastAPI /auth/me.
 * Accepts a Request, a next/headers cookie store, or a raw Cookie header; with no
 * argument it reads the current request's cookies (server components only).
 */
export async function getServerSession(source, fetchImpl = fetch) {
  const cookieHeader = cookieHeaderFrom(source ?? (await defaultCookieSource()));
  if (!hasSessionCookie(cookieHeader)) {
    return { user: null, reason: "signed_out" };
  }

  let response;
  try {
    response = await fetchImpl(`${getApiBaseUrl()}/auth/me`, {
      method: "GET",
      headers: { Cookie: cookieHeader },
      cache: "no-store",
    });
  } catch {
    return { user: null, reason: "unavailable" };
  }

  if (response.status === 401) return { user: null, reason: "signed_out" };
  if (response.status === 403) return { user: null, reason: "suspended" };
  if (!response.ok) return { user: null, reason: "unavailable" };

  const user = await response.json().catch(() => null);
  if (!user) return { user: null, reason: "unavailable" };
  return { user };
}

async function defaultRedirect(location) {
  const { redirect } = await import("next/navigation");
  redirect(location);
}

/** Server components only: returns the admin user or redirects away. */
export async function requireAdminPage(nextPath = "/admin", options = {}) {
  const { cookieSource, fetchImpl = fetch, redirectImpl = defaultRedirect } = options;
  const session = await getServerSession(cookieSource, fetchImpl);

  if (!session.user && session.reason === "signed_out") {
    const next = encodeURIComponent(sanitizeNextPath(nextPath));
    await redirectImpl(`/login?next=${next}`);
  }
  if (session.user?.role !== "admin") {
    await redirectImpl("/jobs");
  }
  return session.user;
}
