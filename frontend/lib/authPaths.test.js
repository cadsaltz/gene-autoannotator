import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import assert from "node:assert/strict";
import { isAdminPath, isPublicPath, isProtectedPath, sanitizeNextPath } from "./authPaths.js";

test("guide and auth pages are public", () => {
  assert.equal(isPublicPath("/"), true);
  assert.equal(isPublicPath("/login"), true);
  assert.equal(isPublicPath("/signup"), true);
  assert.equal(isPublicPath("/auth/verify"), true);
});

test("legal pages are public", () => {
  assert.equal(isPublicPath("/legal/terms"), true);
  assert.equal(isPublicPath("/legal/privacy"), true);
  assert.equal(isProtectedPath("/legal/terms"), false);
});

test("workbench pages are protected", () => {
  assert.equal(isProtectedPath("/jobs"), true);
  assert.equal(isProtectedPath("/fleet"), true);
  assert.equal(isProtectedPath("/profiles"), true);
  assert.equal(isProtectedPath("/annotations"), true);
  assert.equal(isProtectedPath("/admin"), true);
  assert.equal(isProtectedPath("/admin/users"), true);
});

test("fleet and admin pages are admin-only", () => {
  assert.equal(isAdminPath("/fleet"), true);
  assert.equal(isAdminPath("/admin"), true);
  assert.equal(isAdminPath("/admin/users"), true);
  assert.equal(isAdminPath("/jobs"), false);
  assert.equal(isAdminPath("/profiles"), false);
  assert.equal(isAdminPath("/administrator"), false);
});

test("middleware matcher covers admin pages", async () => {
  const middleware = await readFile(path.join(process.cwd(), "middleware.js"), "utf8");
  assert.match(middleware, /"\/admin\/:path\*"/);
});

test("sanitizeNextPath allows same-origin paths and blocks open redirects", () => {
  assert.equal(sanitizeNextPath("/jobs"), "/jobs");
  assert.equal(sanitizeNextPath("/annotations/foo"), "/annotations/foo");
  assert.equal(sanitizeNextPath("//evil.example"), "/jobs");
  assert.equal(sanitizeNextPath("https://evil.example"), "/jobs");
  assert.equal(sanitizeNextPath(""), "/jobs");
  assert.equal(sanitizeNextPath(null), "/jobs");
});

test("login and signup forward sanitized next to verify", async () => {
  const authForms = await readFile(
    path.join(process.cwd(), "components/AuthForms.js"),
    "utf8",
  );
  assert.match(authForms, /function verifyPageUrl\(email, nextRaw\)/);
  assert.match(authForms, /sanitizeNextPath\(nextRaw\)/);
  assert.match(authForms, /verifyPageUrl\(email, searchParams\.get\("next"\)\)/);
});
