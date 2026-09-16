import { NextResponse } from "next/server";

import { getApiBaseUrl } from "./api.js";

/**
 * Soft server-side session check: forward Cookie to FastAPI /auth/me.
 * Returns a 401 NextResponse when unauthenticated; otherwise null.
 */
export async function requireAnnotationSession(request, fetchImpl = fetch) {
  const cookie = request.headers.get("cookie") || "";
  try {
    const response = await fetchImpl(`${getApiBaseUrl()}/auth/me`, {
      method: "GET",
      headers: cookie ? { Cookie: cookie } : {},
      cache: "no-store",
    });
    if (response.ok) {
      return null;
    }
  } catch {
    // Treat backend/auth failures as unauthenticated for annotation APIs.
  }
  return NextResponse.json({ detail: "Authentication required" }, { status: 401 });
}
