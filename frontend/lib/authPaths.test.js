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
