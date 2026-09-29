import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

import { navItemsFor } from "../lib/navItems.js";

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
