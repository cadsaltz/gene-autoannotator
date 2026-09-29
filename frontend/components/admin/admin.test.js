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
  assert.deepEqual(selfRowRestrictions({ id: "me" }, "me"), {
    isSelf: true,
    canChangeRole: false,
    canChangeStatus: false,
    canDelete: false,
  });
  assert.deepEqual(selfRowRestrictions({ id: "other" }, "me"), {
    isSelf: false,
    canChangeRole: true,
    canChangeStatus: true,
    canDelete: true,
  });
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
  for (const action of ["role_change", "status_change", "quota_change", "user_delete", "login"]) {
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
