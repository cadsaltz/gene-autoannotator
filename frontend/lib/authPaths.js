export function isPublicPath(pathname) {
  if (pathname === "/") return true;
  if (pathname.startsWith("/login")) return true;
  if (pathname.startsWith("/signup")) return true;
  if (pathname.startsWith("/auth/")) return true;
  return false;
}

export function isProtectedPath(pathname) {
  return (
    pathname.startsWith("/jobs") ||
    pathname.startsWith("/fleet") ||
    pathname.startsWith("/profiles") ||
    pathname.startsWith("/annotations")
  );
}

/** Allow only same-origin relative paths; block protocol-relative open redirects. */
export function sanitizeNextPath(next, fallback = "/jobs") {
  if (typeof next !== "string") return fallback;
  if (next.startsWith("/") && !next.startsWith("//")) return next;
  return fallback;
}
