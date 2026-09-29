export const QUOTA_FIELDS = [
  { key: "quota_max_active", label: "Active jobs", defaultKey: "user_max_active" },
  { key: "quota_max_per_day", label: "Jobs / 24 h", defaultKey: "user_max_per_day" },
  { key: "quota_max_batch", label: "Batch size", defaultKey: "user_max_batch" },
];

export const ROLES = ["user", "admin"];
export const STATUSES = ["active", "suspended"];

export const AUDIT_ACTIONS = [
  "signup",
  "login_code_sent",
  "login",
  "logout",
  "job_submit",
  "batch_submit",
  "job_cancel",
  "profile_create",
  "profile_update",
  "profile_delete",
  "role_change",
  "status_change",
  "quota_change",
  "sessions_revoked",
  "user_delete",
];

export function draftFromUser(user) {
  const draft = { role: user.role, status: user.status };
  for (const { key } of QUOTA_FIELDS) {
    draft[key] = user[key] === null || user[key] === undefined ? "" : String(user[key]);
  }
  return draft;
}

export const MAX_QUOTA = 2147483647;

function parseQuota(raw, label) {
  const text = String(raw ?? "").trim();
  if (text === "") return { value: null };
  if (!/^\d+$/.test(text)) {
    return { error: `${label} must be a whole number of 0 or more, or blank for the default.` };
  }
  const value = Number(text);
  if (value > MAX_QUOTA) return { error: `${label} must be at most ${MAX_QUOTA}.` };
  return { value };
}

/** Returns `{ patch }` with only changed fields (blank quota → null), or `{ error }`. */
export function buildUserPatch(user, draft) {
  const patch = {};
  if (draft.role !== user.role) patch.role = draft.role;
  if (draft.status !== user.status) patch.status = draft.status;
  for (const { key, label } of QUOTA_FIELDS) {
    const parsed = parseQuota(draft[key], label);
    if (parsed.error) return { error: parsed.error };
    if (parsed.value !== (user[key] ?? null)) patch[key] = parsed.value;
  }
  return { patch };
}

export function hasUnsavedDrafts(users, drafts) {
  return users.some((user) => {
    const draft = drafts[user.id];
    if (!draft) return false;
    const result = buildUserPatch(user, draft);
    return Boolean(result.error) || Object.keys(result.patch).length > 0;
  });
}

export function quotaPlaceholder(defaultValue) {
  if (typeof defaultValue !== "number") return "Default";
  return defaultValue > 0 ? `Default (${defaultValue})` : "Default (unlimited)";
}

export function formatQuotaLimit(value) {
  if (typeof value !== "number") return "—";
  return value > 0 ? String(value) : "Unlimited";
}

const SELF_LOCKED_REASON =
  "You can't change the role or status of, or delete, your own account here. Ask another admin, " +
  "or on the server run `python -m backend.manage set-role EMAIL {user,admin}` " +
  "(or `set-status EMAIL {active,suspended}`).";

export function selfRowRestrictions(user, currentUserId) {
  const isSelf = Boolean(currentUserId) && user.id === currentUserId;
  return {
    isSelf,
    canChangeRole: !isSelf,
    canChangeStatus: !isSelf,
    canDelete: !isSelf,
    lockedReason: isSelf ? SELF_LOCKED_REASON : null,
  };
}

export function formatAuditDetails(details) {
  if (!details || (typeof details === "object" && Object.keys(details).length === 0)) return "";
  return JSON.stringify(details);
}

export function formatAuditTarget(event) {
  return [event.target_type, event.target_id].filter(Boolean).join(" ");
}

export function formatLocalTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}
