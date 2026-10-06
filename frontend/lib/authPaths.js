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

/** `/login` URL that returns to `nextPath` (pathname plus query) after sign-in. */
export function loginPathFor(nextPath) {
  return `/login?next=${encodeURIComponent(sanitizeNextPath(nextPath))}`;
}

/** Auth page link that carries a sanitized `next` forward when one was supplied. */
export function authLinkWithNext(base, nextRaw) {
  if (!nextRaw) return base;
  return `${base}?next=${encodeURIComponent(sanitizeNextPath(nextRaw))}`;
}

/** `/signup` URL with the email prefilled, carrying a sanitized `next` forward. */
export function signupPathFor(email, nextRaw) {
  const params = new URLSearchParams();
  const trimmed = (email || "").trim();
  if (trimmed) params.set("email", trimmed);
  if (nextRaw) params.set("next", sanitizeNextPath(nextRaw));
  const query = params.toString();
  return query ? `/signup?${query}` : "/signup";
}
