import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import assert from "node:assert/strict";
import {
  authLinkWithNext,
  isPublicPath,
  isProtectedPath,
  loginPathFor,
  sanitizeNextPath,
} from "./authPaths.js";

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

test("middleware matcher covers admin pages", async () => {
  const middleware = await readFile(path.join(process.cwd(), "middleware.js"), "utf8");
  assert.match(middleware, /"\/admin\/:path\*"/);
});

test("middleware sends pathname plus query string through loginPathFor", async () => {
  const middleware = await readFile(path.join(process.cwd(), "middleware.js"), "utf8");
  assert.match(middleware, /const \{ pathname, search \} = request\.nextUrl;/);
  assert.match(middleware, /loginPathFor\(`\$\{pathname\}\$\{search\}`\)/);
});

test("loginPathFor keeps the query string and sanitizes next", () => {
  assert.equal(loginPathFor("/annotations?query=dnaA"), "/login?next=%2Fannotations%3Fquery%3DdnaA");
  assert.equal(loginPathFor("/jobs"), "/login?next=%2Fjobs");
  assert.equal(loginPathFor("//evil.example"), "/login?next=%2Fjobs");
  assert.equal(loginPathFor("/annotations?q=%5Cevil"), "/login?next=%2Fjobs");
});

test("authLinkWithNext forwards a sanitized next only when one was given", () => {
  assert.equal(authLinkWithNext("/signup", null), "/signup");
  assert.equal(authLinkWithNext("/signup", ""), "/signup");
  assert.equal(authLinkWithNext("/login", "/annotations?query=a"), "/login?next=%2Fannotations%3Fquery%3Da");
  assert.equal(authLinkWithNext("/login", "https://evil.example"), "/login?next=%2Fjobs");
});

test("isAdminPath is no longer exported", async () => {
  const authPaths = await import("./authPaths.js");
  assert.equal("isAdminPath" in authPaths, false);
});

test("auth forms cross-link sign in and sign up with the sanitized next", async () => {
  const authForms = await readFile(path.join(process.cwd(), "components/AuthForms.js"), "utf8");
  assert.match(authForms, /href=\{authLinkWithNext\("\/login", searchParams\.get\("next"\)\)\}/);
  assert.match(authForms, /href=\{authLinkWithNext\("\/signup", searchParams\.get\("next"\)\)\}/);
});

test("verify page shows the console email hint only outside production", async () => {
  const authForms = await readFile(path.join(process.cwd(), "components/AuthForms.js"), "utf8");
  assert.match(authForms, /process\.env\.NODE_ENV !== "production"/);
  assert.match(
    authForms,
    /\{SHOW_CONSOLE_EMAIL_HINT \? \([\s\S]*EMAIL_BACKEND=console[\s\S]*\) : null\}/,
  );
});

test("sanitizeNextPath allows same-origin paths and blocks open redirects", () => {
  assert.equal(sanitizeNextPath("/jobs"), "/jobs");
  assert.equal(sanitizeNextPath("/annotations/foo"), "/annotations/foo");
  assert.equal(sanitizeNextPath("//evil.example"), "/jobs");
  assert.equal(sanitizeNextPath("https://evil.example"), "/jobs");
  assert.equal(sanitizeNextPath(""), "/jobs");
  assert.equal(sanitizeNextPath(null), "/jobs");
});

test("sanitizeNextPath rejects backslash, control, and encoded protocol-relative tricks", () => {
  assert.equal(sanitizeNextPath("/\\evil.example"), "/jobs");
  assert.equal(sanitizeNextPath("/jobs\\..\\evil"), "/jobs");
  assert.equal(sanitizeNextPath("\\\\evil.example"), "/jobs");
  assert.equal(sanitizeNextPath(" /jobs"), "/jobs");
  assert.equal(sanitizeNextPath("\t//evil.example"), "/jobs");
  assert.equal(sanitizeNextPath("/\t/evil.example"), "/jobs");
  assert.equal(sanitizeNextPath("/\n/evil.example"), "/jobs");
  assert.equal(sanitizeNextPath("/%5Cevil.example"), "/jobs");
  assert.equal(sanitizeNextPath("/%5cevil.example"), "/jobs");
  assert.equal(sanitizeNextPath("/%2Fevil.example"), "/jobs");
  assert.equal(sanitizeNextPath("/%2F%2Fevil.example"), "/jobs");
  assert.equal(sanitizeNextPath("/%E0%A4%A"), "/jobs");
  assert.equal(sanitizeNextPath("/admin/users"), "/admin/users");
  assert.equal(sanitizeNextPath("/annotations?query=a%20b"), "/annotations?query=a%20b");
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
