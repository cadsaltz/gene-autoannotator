import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

import { isNavItemActive, navItemsFor } from "../lib/navItems.js";

const projectRoot = process.cwd();

async function readProjectFile(relativePath) {
  return readFile(path.join(projectRoot, relativePath), "utf8");
}

test("AppShell hides workbench links until signed in", async () => {
  const workspace = await readProjectFile("components/AppShell.js");
  assert.match(workspace, /getMe|useAuth|signedIn|email_verified/);
  assert.match(workspace, /Sign in|Sign out|signup|login/i);
});

test("navItemsFor shows guide and auth links when signed out", () => {
  assert.deepEqual(navItemsFor(null), [
    { href: "/", label: "Guide" },
    { href: "/login", label: "Sign in" },
    { href: "/signup", label: "Sign up" },
  ]);
});

test("navItemsFor shows the user workbench without admin pages", () => {
  assert.deepEqual(navItemsFor({ role: "user", status: "active" }), [
    { href: "/", label: "Guide" },
    { href: "/jobs", label: "Jobs" },
    { href: "/profiles", label: "Profiles" },
    { href: "/annotations", label: "Annotations" },
  ]);
});

test("navItemsFor shows fleet and admin pages to admins", () => {
  assert.deepEqual(navItemsFor({ role: "admin", status: "active" }), [
    { href: "/", label: "Guide" },
    { href: "/jobs", label: "Jobs" },
    { href: "/fleet", label: "Fleet & Health" },
    { href: "/profiles", label: "Profiles" },
    { href: "/annotations", label: "Annotations" },
    { href: "/admin", label: "Admin" },
  ]);
});

test("navItemsFor treats unknown roles as regular users", () => {
  assert.deepEqual(
    navItemsFor({ status: "active" }).map((item) => item.href),
    ["/", "/jobs", "/profiles", "/annotations"],
  );
});

test("AppShell uses role-aware navigation", async () => {
  const shell = await readProjectFile("components/AppShell.js");
  assert.match(shell, /navItemsFor\(/);
  assert.doesNotMatch(shell, /const navItems = \[/);
});

test("isNavItemActive highlights a section for its nested paths on segment boundaries", () => {
  assert.equal(isNavItemActive("/admin", "/admin"), true);
  assert.equal(isNavItemActive("/admin/users", "/admin"), true);
  assert.equal(isNavItemActive("/admin/audit/", "/admin"), true);
  assert.equal(isNavItemActive("/annotations/xyz", "/annotations"), true);
  assert.equal(isNavItemActive("/administrator", "/admin"), false);
  assert.equal(isNavItemActive("/jobs", "/admin"), false);
});

test("isNavItemActive matches the guide only on the exact root path", () => {
  assert.equal(isNavItemActive("/", "/"), true);
  assert.equal(isNavItemActive("/jobs", "/"), false);
  assert.equal(isNavItemActive(null, "/"), false);
  assert.equal(isNavItemActive(null, "/admin"), false);
});

test("AppShell highlights nav items with isNavItemActive", async () => {
  const shell = await readProjectFile("components/AppShell.js");
  assert.match(shell, /isNavItemActive\(pathname, item\.href\)/);
  assert.doesNotMatch(shell, /pathname === item\.href/);
});

test("fleet page requires an admin before rendering", async () => {
  const page = await readProjectFile("app/fleet/page.js");
  assert.doesNotMatch(page, /"use client"/);
  assert.match(page, /await requireAdminPage\("\/fleet"\)/);
});

test("AppShell does not mount page content until the session check finishes", async () => {
  const shell = await readProjectFile("components/AppShell.js");
  assert.match(shell, /loading \? \(?\s*<SessionLoading \/>/);
  assert.match(shell, /function SessionLoading\(/);
});

test("AppShell replaces page content with a suspended card on 403", async () => {
  const shell = await readProjectFile("components/AppShell.js");
  assert.match(shell, /status === 403/);
  assert.match(shell, /This account is suspended/);
  assert.match(shell, /Contact the site administrators/);
});

test("AppShell supports a full-width content area", async () => {
  const shell = await readProjectFile("components/AppShell.js");
  assert.match(shell, /export default function AppShell\(\{ children, publicPage = false, fullWidth = false \}\)/);
  assert.match(shell, /fullWidth \? "w-full flex-1" : "mx-auto w-full max-w-7xl flex-1 px-6 py-8"/);
});

test("AppShell header has the theme switch on every page", async () => {
  const shell = await readProjectFile("components/AppShell.js");
  assert.match(shell, /import ThemeToggle from "\.\/ThemeToggle"/);
  assert.match(shell, /<ThemeToggle \/>/);
  assert.doesNotMatch(shell, /workbench-nav/);
});

test("ThemeToggle offers light, dark, and system and persists the choice", async () => {
  const toggle = await readProjectFile("components/ThemeToggle.js");
  assert.match(toggle, /"use client"/);
  assert.match(toggle, /role="group"/);
  assert.match(toggle, /aria-pressed=\{choice === option\.value\}/);
  assert.match(toggle, /localStorage\.setItem\(THEME_STORAGE_KEY, next\)/);
  assert.match(toggle, /useSyncExternalStore\(subscribe, readChoice, \(\) => "system"\)/);
  for (const value of ["light", "dark", "system"]) {
    assert.match(toggle, new RegExp(`value: "${value}"`));
  }
});
