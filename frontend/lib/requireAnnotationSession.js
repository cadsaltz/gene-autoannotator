import { getServerSession } from "./session.js";

function denied(status, detail) {
  return { user: null, response: Response.json({ detail }, { status }) };
}

/**
 * Route-handler session gate for the Mongo-backed annotation APIs.
 * Returns `{ user, response: null }` when allowed, otherwise `{ user: null, response }`
 * with a 401 (signed out / auth unavailable) or 403 (suspended, or non-admin when `admin`).
 */
export async function requireAnnotationSession(request, { admin = false, fetchImpl = fetch } = {}) {
  const session = await getServerSession(request, fetchImpl);
  if (!session.user) {
    if (session.reason === "suspended") return denied(403, "Account suspended");
    return denied(401, "Authentication required");
  }
  if (admin && session.user.role !== "admin") {
    return denied(403, "Admin access required");
  }
  return { user: session.user, response: null };
}
