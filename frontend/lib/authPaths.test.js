import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import assert from "node:assert/strict";
import { isPublicPath, isProtectedPath, sanitizeNextPath } from "./authPaths.js";

test("guide and auth pages are public", () => {
  assert.equal(isPublicPath("/"), true);
  assert.equal(isPublicPath("/login"), true);
  assert.equal(isPublicPath("/signup"), true);
  assert.equal(isPublicPath("/auth/verify"), true);
});

test("workbench pages are protected", () => {
  assert.equal(isProtectedPath("/jobs"), true);
  assert.equal(isProtectedPath("/fleet"), true);
  assert.equal(isProtectedPath("/profiles"), true);
  assert.equal(isProtectedPath("/annotations"), true);
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
