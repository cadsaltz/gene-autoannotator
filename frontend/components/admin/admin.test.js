import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

import {
  AUDIT_ACTIONS,
  buildUserPatch,
  draftFromUser,
  formatAuditDetails,
  formatAuditTarget,
  formatLocalTime,
  formatQuotaLimit,
  hasUnsavedDrafts,
  MAX_QUOTA,
  quotaPlaceholder,
  selfRowRestrictions,
} from "../../lib/adminConsole.js";

const projectRoot = process.cwd();

async function readProjectFile(relativePath) {
  return readFile(path.join(projectRoot, relativePath), "utf8");
}

const user = {
  id: "u1",
  email: "a@example.org",
  role: "user",
  status: "active",
  quota_max_active: 5,
  quota_max_per_day: null,
  quota_max_batch: 0,
};

for (const [file, route] of [
  ["app/admin/page.js", "/admin"],
  ["app/admin/users/page.js", "/admin/users"],
  ["app/admin/audit/page.js", "/admin/audit"],
]) {
  test(`${file} requires an admin on the server before rendering`, async () => {
    const page = await readProjectFile(file);
    assert.doesNotMatch(page, /"use client"/);
    assert.match(page, new RegExp(`await requireAdminPage\\("${route.replace(/\//g, "\\/")}"\\)`));
    assert.match(page, /<AppShell>/);
  });
}

test("draftFromUser renders null quota overrides as blank inputs", () => {
  assert.deepEqual(draftFromUser(user), {
    role: "user",
    status: "active",
    quota_max_active: "5",
    quota_max_per_day: "",
    quota_max_batch: "0",
  });
});

test("buildUserPatch sends null for blank quota inputs that had an override", () => {
  const draft = { ...draftFromUser(user), quota_max_active: "  " };
  assert.deepEqual(buildUserPatch(user, draft), { patch: { quota_max_active: null } });
});

test("buildUserPatch sends only changed fields", () => {
  assert.deepEqual(buildUserPatch(user, draftFromUser(user)), { patch: {} });

  const draft = {
    ...draftFromUser(user),
    role: "admin",
    status: "suspended",
    quota_max_per_day: "12",
    quota_max_batch: "0",
  };
  assert.deepEqual(buildUserPatch(user, draft), {
    patch: { role: "admin", status: "suspended", quota_max_per_day: 12 },
  });
});

test("buildUserPatch rejects negative or non-integer quota inputs", () => {
  for (const bad of ["-1", "1.5", "abc", "1e3"]) {
    const draft = { ...draftFromUser(user), quota_max_per_day: bad };
    const result = buildUserPatch(user, draft);
    assert.equal(result.patch, undefined, bad);
    assert.match(result.error, /whole number/i, bad);
  }
});

test("quotaPlaceholder shows the default or unlimited when the default is 0 or less", () => {
  assert.equal(quotaPlaceholder(20), "Default (20)");
  assert.equal(quotaPlaceholder(0), "Default (unlimited)");
  assert.equal(quotaPlaceholder(-1), "Default (unlimited)");
  assert.equal(quotaPlaceholder(undefined), "Default");
});

test("formatQuotaLimit shows unlimited for 0 or less", () => {
  assert.equal(formatQuotaLimit(25), "25");
  assert.equal(formatQuotaLimit(0), "Unlimited");
  assert.equal(formatQuotaLimit(undefined), "—");
});

test("selfRowRestrictions locks role, status, and delete on the admin's own row", () => {
  const self = selfRowRestrictions({ id: "me" }, "me");
  assert.equal(self.isSelf, true);
  assert.equal(self.canChangeRole, false);
  assert.equal(self.canChangeStatus, false);
  assert.equal(self.canDelete, false);
  assert.deepEqual(selfRowRestrictions({ id: "other" }, "me"), {
    isSelf: false,
    canChangeRole: true,
    canChangeStatus: true,
    canDelete: true,
    lockedReason: null,
  });
});

test("selfRowRestrictions explains the lock and points to the manage CLI", () => {
  const { lockedReason } = selfRowRestrictions({ id: "me" }, "me");
  assert.match(lockedReason, /your own account/i);
  assert.match(lockedReason, /python -m backend\.manage set-role EMAIL \{user,admin\}/);
  assert.match(lockedReason, /another admin/i);
});

test("buildUserPatch rejects quotas above the backend's 32-bit limit", () => {
  assert.equal(MAX_QUOTA, 2147483647);
  const ok = buildUserPatch(user, { ...draftFromUser(user), quota_max_per_day: "2147483647" });
  assert.deepEqual(ok, { patch: { quota_max_per_day: 2147483647 } });

  const tooBig = buildUserPatch(user, { ...draftFromUser(user), quota_max_per_day: "2147483648" });
  assert.equal(tooBig.patch, undefined);
  assert.match(tooBig.error, /at most 2147483647/);
});

test("buildUserPatch rejects partial numeric text instead of clearing the override", () => {
  for (const bad of ["5e", "-", "+3", "3 4"]) {
    const result = buildUserPatch(user, { ...draftFromUser(user), quota_max_active: bad });
    assert.equal(result.patch, undefined, bad);
    assert.match(result.error, /whole number/i, bad);
  }
});

test("hasUnsavedDrafts detects changed or invalid rows", () => {
  const other = { ...user, id: "u2" };
  const clean = { u1: draftFromUser(user), u2: draftFromUser(other) };
  assert.equal(hasUnsavedDrafts([user, other], clean), false);
  assert.equal(hasUnsavedDrafts([user, other], {}), false);
  assert.equal(
    hasUnsavedDrafts([user, other], { ...clean, u2: { ...clean.u2, role: "admin" } }),
    true,
  );
  assert.equal(
    hasUnsavedDrafts([user, other], { ...clean, u1: { ...clean.u1, quota_max_batch: "x" } }),
    true,
  );
});

test("UsersTable quota inputs are text so invalid entries reach the parser", async () => {
  const table = await readProjectFile("components/admin/UsersTable.js");
  assert.doesNotMatch(table, /type="number"/);
  assert.match(table, /type="text"\s+inputMode="numeric"/);
});

test("UsersTable shows the accepted terms version read-only", async () => {
  const table = await readProjectFile("components/admin/UsersTable.js");
  assert.match(table, /user\.terms_version\s*\?/);
  assert.match(table, /formatLocalTime\(user\.terms_accepted_at\)/);
  assert.match(table, /Terms not recorded/);
});

test("UsersTable confirms before revoking the admin's own sessions", async () => {
  const table = await readProjectFile("components/admin/UsersTable.js");
  assert.match(
    table,
    /async function handleRevoke\(user\) \{[\s\S]*?selfRowRestrictions\(user, currentUserId\)\.isSelf[\s\S]*?window\.confirm\([\s\S]*?\)[\s\S]*?adminRevokeSessions\(user\.id\)/,
  );
});

test("UsersTable shows the lock reason on disabled self-row controls", async () => {
  const table = await readProjectFile("components/admin/UsersTable.js");
  const titles = table.match(/title=\{restrictions\.lockedReason \?\? undefined\}/g) || [];
  assert.equal(titles.length, 3);
  assert.match(table, /\{restrictions\.lockedReason\}/);
});

test("UsersTable confirms before a search discards unsaved drafts", async () => {
  const table = await readProjectFile("components/admin/UsersTable.js");
  assert.match(
    table,
    /function handleSearch\(event\) \{[\s\S]*?hasUnsavedDrafts\(users, drafts\)[\s\S]*?window\.confirm\([\s\S]*?\)[\s\S]*?load\(/,
  );
});

test("UsersTable drops drafts, messages, and pending state for deleted users", async () => {
  const table = await readProjectFile("components/admin/UsersTable.js");
  const handler = table.match(/async function handleDelete\(user\) \{[\s\S]*?\n {2}\}\n/)?.[0] || "";
  assert.match(handler, /setDrafts\(\(current\) => withoutKey\(current, user\.id\)\)/);
  assert.match(handler, /setMessages\(\(current\) => withoutKey\(current, user\.id\)\)/);
  assert.match(handler, /setPending\(\(current\) => withoutKey\(current, user\.id\)\)/);
});

test("formatAuditDetails renders compact JSON and blanks empty details", () => {
  assert.equal(formatAuditDetails({ from: "user", to: "admin" }), '{"from":"user","to":"admin"}');
  assert.equal(formatAuditDetails({}), "");
  assert.equal(formatAuditDetails(null), "");
});

test("formatAuditTarget joins type and id", () => {
  assert.equal(formatAuditTarget({ target_type: "user", target_id: "u1" }), "user u1");
  assert.equal(formatAuditTarget({ target_type: null, target_id: null }), "");
});

test("AUDIT_ACTIONS lists the admin actions for the filter", () => {
  for (const action of [
    "role_change", "status_change", "quota_change", "user_delete", "login", "jobs_cancelled",
  ]) {
    assert.ok(AUDIT_ACTIONS.includes(action), action);
  }
});

test("UsersTable saves each row with buildUserPatch and a per-row pending state", async () => {
  const table = await readProjectFile("components/admin/UsersTable.js");
  assert.match(table, /"use client";/);
  assert.match(table, /buildUserPatch\(user, draft\)/);
  assert.match(table, /await adminUpdateUser\(user\.id, result\.patch\)/);
  assert.match(table, /pending=\{Boolean\(pending\[user\.id\]\)\}/);
  assert.match(table, /disabled=\{pending/);
  assert.match(table, /quotaPlaceholder\(/);
  assert.match(table, /selfRowRestrictions\(/);
});

test("UsersTable confirms before deleting and surfaces backend errors inline", async () => {
  const table = await readProjectFile("components/admin/UsersTable.js");
  assert.match(table, /window\.confirm\([\s\S]*?\)[\s\S]*?adminDeleteUser\(user\.id\)/);
  assert.match(table, /adminRevokeSessions\(user\.id\)/);
  assert.match(table, /adminListUsers\(/);
  assert.match(table, /error\.message/);
  assert.match(table, /role="alert"/);
});

test("AdminOverview shows queue, worker, user, and quota stats with console links", async () => {
  const overview = await readProjectFile("components/admin/AdminOverview.js");
  assert.match(overview, /adminOverview\(/);
  for (const field of [
    "queued",
    "running",
    "completed_24h",
    "failed_24h",
    "workers_online",
    "users_total",
    "users_suspended",
    "quota_config",
  ]) {
    assert.match(overview, new RegExp(`\\.${field}\\b`), field);
  }
  for (const href of ["/admin/users", "/admin/audit", "/jobs", "/fleet"]) {
    assert.match(overview, new RegExp(`href(=|: )"${href.replace(/\//g, "\\/")}"`), href);
  }
});

test("AuditTable filters by action and user and shows local times", async () => {
  const audit = await readProjectFile("components/admin/AuditTable.js");
  assert.match(audit, /adminAudit\(\{[^}]*action[^}]*user_id[^}]*\}\)|adminAudit\(\{[^}]*user_id[^}]*action[^}]*\}\)/);
  assert.match(audit, /AUDIT_ACTIONS/);
  assert.match(audit, /formatAuditDetails\(/);
  assert.match(audit, /formatLocalTime\(event\.created_at\)/);
});

test("formatLocalTime renders ISO timestamps in local time and tolerates bad input", () => {
  const iso = "2026-09-29T12:34:56+00:00";
  assert.equal(formatLocalTime(iso), new Date(iso).toLocaleString());
  assert.equal(formatLocalTime("not a date"), "not a date");
  assert.equal(formatLocalTime(null), "—");
});
