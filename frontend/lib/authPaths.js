function matchesSection(pathname, section) {
  return pathname === section || pathname.startsWith(`${section}/`);
}

export function isPublicPath(pathname) {
  if (pathname === "/") return true;
  if (pathname.startsWith("/login")) return true;
  if (pathname.startsWith("/signup")) return true;
  if (pathname.startsWith("/auth/")) return true;
  if (matchesSection(pathname, "/legal")) return true;
  return false;
}

export function isProtectedPath(pathname) {
  return (
    pathname.startsWith("/jobs") ||
    pathname.startsWith("/fleet") ||
    pathname.startsWith("/profiles") ||
    pathname.startsWith("/annotations") ||
    matchesSection(pathname, "/admin")
  );
}

export function isAdminPath(pathname) {
  return matchesSection(pathname, "/fleet") || matchesSection(pathname, "/admin");
}

const CONTROL_CHARS = /[\u0000-\u001f\u007f]/;

function isSafeRelativePath(value) {
  if (!value.startsWith("/") || value.startsWith("//")) return false;
  // Browsers treat "\" as "/" and strip tabs/newlines, so "/\evil" or "/\t/evil" become "//evil".
  if (value.includes("\\")) return false;
  if (CONTROL_CHARS.test(value)) return false;
  return true;
}

/** Allow only same-origin relative paths; block protocol-relative open redirects. */
export function sanitizeNextPath(next, fallback = "/jobs") {
  if (typeof next !== "string") return fallback;
  if (!isSafeRelativePath(next)) return fallback;
  let decoded;
  try {
    decoded = decodeURIComponent(next);
  } catch {
    return fallback;
  }
  if (!isSafeRelativePath(decoded)) return fallback;
  return next;
}
