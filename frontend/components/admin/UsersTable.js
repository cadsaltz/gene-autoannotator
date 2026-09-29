"use client";

import Link from "next/link";
import { Fragment, useCallback, useEffect, useRef, useState } from "react";

import {
  QUOTA_FIELDS,
  ROLES,
  STATUSES,
  buildUserPatch,
  draftFromUser,
  formatLocalTime,
  quotaPlaceholder,
  selfRowRestrictions,
} from "../../lib/adminConsole";
import {
  adminDeleteUser,
  adminListUsers,
  adminOverview,
  adminRevokeSessions,
  adminUpdateUser,
} from "../../lib/api";

function draftsFor(users) {
  return Object.fromEntries(users.map((user) => [user.id, draftFromUser(user)]));
}

function UserRow({
  user,
  draft,
  quotaDefaults,
  currentUserId,
  pending,
  message,
  onDraftChange,
  onSave,
  onRevoke,
  onDelete,
}) {
  const restrictions = selfRowRestrictions(user, currentUserId);
  const result = buildUserPatch(user, draft);
  const dirty = Boolean(result.error) || Object.keys(result.patch).length > 0;

  return (
    <Fragment>
      <tr className="border-t workbench-border">
        <td className="px-3 py-3 align-top">
          <p className="workbench-foreground font-semibold">
            {user.email}
            {restrictions.isSelf ? (
              <span className="workbench-muted-bg ml-2 rounded-full border workbench-border px-2 py-0.5 text-xs font-bold uppercase tracking-wide">
                You
              </span>
            ) : null}
          </p>
          <p className="workbench-muted text-xs">{user.username || "no username"}</p>
          <p className="workbench-muted mt-1 text-xs">
            Joined {formatLocalTime(user.created_at)} · Last sign-in{" "}
            {formatLocalTime(user.last_login_at)}
          </p>
        </td>
        <td className="px-3 py-3 align-top">
          <label className="sr-only" htmlFor={`role-${user.id}`}>
            Role for {user.email}
          </label>
          <select
            id={`role-${user.id}`}
            value={draft.role}
            onChange={(event) => onDraftChange(user.id, { role: event.target.value })}
            disabled={pending || !restrictions.canChangeRole}
            title={restrictions.isSelf ? "You cannot change your own role" : undefined}
            className="workbench-input disabled:opacity-60"
          >
            {ROLES.map((role) => (
              <option key={role} value={role}>
                {role}
              </option>
            ))}
          </select>
        </td>
        <td className="px-3 py-3 align-top">
          <label className="sr-only" htmlFor={`status-${user.id}`}>
            Status for {user.email}
          </label>
          <select
            id={`status-${user.id}`}
            value={draft.status}
            onChange={(event) => onDraftChange(user.id, { status: event.target.value })}
            disabled={pending || !restrictions.canChangeStatus}
            title={restrictions.isSelf ? "You cannot suspend yourself" : undefined}
            className="workbench-input disabled:opacity-60"
          >
            {STATUSES.map((status) => (
              <option key={status} value={status}>
                {status}
              </option>
            ))}
          </select>
        </td>
        <td className="px-3 py-3 align-top">
          <div className="grid gap-2">
            {QUOTA_FIELDS.map((field) => (
              <label key={field.key} className="flex items-center justify-between gap-2 text-xs">
                <span className="workbench-muted whitespace-nowrap font-semibold">
                  {field.label}
                </span>
                <input
                  type="number"
                  min="0"
                  step="1"
                  value={draft[field.key]}
                  placeholder={quotaPlaceholder(quotaDefaults?.[field.defaultKey])}
                  onChange={(event) =>
                    onDraftChange(user.id, { [field.key]: event.target.value })
                  }
                  disabled={pending}
                  className="workbench-input w-36 text-sm disabled:opacity-60"
                />
              </label>
            ))}
          </div>
        </td>
        <td className="workbench-muted px-3 py-3 align-top text-xs">
          <p>{user.active_jobs} active</p>
          <p>{user.jobs_24h} in 24 h</p>
          <Link
            href={`/admin/audit?user_id=${encodeURIComponent(user.id)}`}
            className="workbench-green mt-2 inline-block font-bold"
          >
            Audit
          </Link>
        </td>
        <td className="px-3 py-3 align-top">
          <div className="flex flex-col items-stretch gap-2">
            <button
              type="button"
              onClick={() => onSave(user)}
              disabled={pending || !dirty}
              className="workbench-button workbench-button-primary disabled:cursor-not-allowed disabled:opacity-50"
            >
              {pending ? "Saving…" : "Save"}
            </button>
            <button
              type="button"
              onClick={() => onRevoke(user)}
              disabled={pending}
              className="workbench-button workbench-button-secondary disabled:cursor-not-allowed disabled:opacity-50"
            >
              Revoke sessions
            </button>
            <button
              type="button"
              onClick={() => onDelete(user)}
              disabled={pending || !restrictions.canDelete}
              title={restrictions.isSelf ? "You cannot delete your own account" : undefined}
              className="workbench-button workbench-button-secondary disabled:cursor-not-allowed disabled:opacity-50"
            >
              Delete
            </button>
          </div>
        </td>
      </tr>
      {message ? (
        <tr>
          <td colSpan={6} className="px-3 pb-3">
            <p
              role={message.error ? "alert" : "status"}
              className={`rounded-xl border workbench-border p-3 text-sm ${
                message.error ? "workbench-amber-bg text-[#5f4b2e]" : "workbench-muted-bg"
              }`}
            >
              {message.text}
            </p>
          </td>
        </tr>
      ) : null}
    </Fragment>
  );
}

export default function UsersTable({ currentUserId }) {
  const [query, setQuery] = useState("");
  const [users, setUsers] = useState([]);
  const [drafts, setDrafts] = useState({});
  const [pending, setPending] = useState({});
  const [messages, setMessages] = useState({});
  const [listError, setListError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const [quotaDefaults, setQuotaDefaults] = useState(null);
  const loadSeq = useRef(0);

  const load = useCallback(async (search) => {
    const seq = ++loadSeq.current;
    setLoading(true);
    try {
      const payload = await adminListUsers(search);
      if (seq !== loadSeq.current) return;
      const rows = payload.users || [];
      setUsers(rows);
      setDrafts(draftsFor(rows));
      setMessages({});
      setListError("");
    } catch (error) {
      if (seq === loadSeq.current) setListError(error.message);
    } finally {
      if (seq === loadSeq.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    async function loadInitialData() {
      await load("");
    }

    loadInitialData();
    adminOverview()
      .then((overview) => setQuotaDefaults(overview.quota_config || null))
      .catch(() => setQuotaDefaults(null));
  }, [load]);

  function setRowMessage(userId, message) {
    setMessages((current) => ({ ...current, [userId]: message }));
  }

  function setRowPending(userId, value) {
    setPending((current) => ({ ...current, [userId]: value }));
  }

  function handleDraftChange(userId, change) {
    setDrafts((current) => ({ ...current, [userId]: { ...current[userId], ...change } }));
    setRowMessage(userId, null);
  }

  async function handleSave(user) {
    const draft = drafts[user.id] || draftFromUser(user);
    const result = buildUserPatch(user, draft);
    if (result.error) {
      setRowMessage(user.id, { error: true, text: result.error });
      return;
    }
    if (Object.keys(result.patch).length === 0) return;
    setRowPending(user.id, true);
    try {
      const updated = await adminUpdateUser(user.id, result.patch);
      setUsers((current) => current.map((row) => (row.id === user.id ? updated : row)));
      setDrafts((current) => ({ ...current, [user.id]: draftFromUser(updated) }));
      setRowMessage(user.id, { error: false, text: "Saved." });
    } catch (error) {
      setRowMessage(user.id, { error: true, text: error.message });
    } finally {
      setRowPending(user.id, false);
    }
  }

  async function handleRevoke(user) {
    setRowPending(user.id, true);
    try {
      const { revoked } = await adminRevokeSessions(user.id);
      setRowMessage(user.id, {
        error: false,
        text: `Revoked ${revoked} session${revoked === 1 ? "" : "s"}.`,
      });
    } catch (error) {
      setRowMessage(user.id, { error: true, text: error.message });
    } finally {
      setRowPending(user.id, false);
    }
  }

  async function handleDelete(user) {
    if (
      !window.confirm(
        `Delete ${user.email}? Their sessions are revoked and queued jobs cancelled. This cannot be undone.`,
      )
    ) {
      return;
    }
    setRowPending(user.id, true);
    try {
      const { cancelled_jobs: cancelled } = await adminDeleteUser(user.id);
      setUsers((current) => current.filter((row) => row.id !== user.id));
      setNotice(
        `Deleted ${user.email}; cancelled ${cancelled} queued job${cancelled === 1 ? "" : "s"}.`,
      );
    } catch (error) {
      setRowMessage(user.id, { error: true, text: error.message });
    } finally {
      setRowPending(user.id, false);
    }
  }

  function handleSearch(event) {
    event.preventDefault();
    setNotice("");
    load(query.trim());
  }

  return (
    <div className="grid gap-5">
      <section className="workbench-card p-6">
        <p className="workbench-kicker">Admin</p>
        <h1 className="workbench-foreground mt-2 text-3xl font-bold tracking-[-0.04em]">Users</h1>
        <p className="workbench-muted mt-3 max-w-2xl text-sm leading-6">
          Change roles and status, override per-user quotas, and revoke sessions. Leave a quota
          blank to use the default; 0 means unlimited. Suspending a user signs them out
          everywhere.
        </p>
        <form onSubmit={handleSearch} className="mt-6 flex flex-wrap gap-2">
          <label className="sr-only" htmlFor="admin-user-search">
            Search users
          </label>
          <input
            id="admin-user-search"
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search by email or username"
            className="workbench-input min-w-64 flex-1"
          />
          <button type="submit" className="workbench-button workbench-button-secondary">
            Search
          </button>
        </form>
        {notice ? (
          <p role="status" className="workbench-muted-bg mt-4 rounded-xl border workbench-border p-3 text-sm">
            {notice}
          </p>
        ) : null}
        {listError ? (
          <p
            role="alert"
            className="workbench-amber-bg mt-4 rounded-xl border workbench-border p-4 text-sm text-[#5f4b2e]"
          >
            {listError}
          </p>
        ) : null}
      </section>

      <section className="workbench-card p-6">
        <p className="workbench-muted text-sm">
          {loading
            ? "Loading users…"
            : `${users.length} user${users.length === 1 ? "" : "s"}`}
        </p>
        {users.length > 0 ? (
          <div className="mt-4 overflow-x-auto rounded-xl border workbench-border">
            <table className="min-w-full text-left text-sm">
              <thead className="workbench-muted-bg workbench-muted text-xs font-bold uppercase tracking-[0.08em]">
                <tr>
                  <th className="px-3 py-2">User</th>
                  <th className="px-3 py-2">Role</th>
                  <th className="px-3 py-2">Status</th>
                  <th className="px-3 py-2">Quota overrides</th>
                  <th className="px-3 py-2">Usage</th>
                  <th className="px-3 py-2">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {users.map((user) => (
                  <UserRow
                    key={user.id}
                    user={user}
                    draft={drafts[user.id] || draftFromUser(user)}
                    quotaDefaults={quotaDefaults}
                    currentUserId={currentUserId}
                    pending={Boolean(pending[user.id])}
                    message={messages[user.id]}
                    onDraftChange={handleDraftChange}
                    onSave={handleSave}
                    onRevoke={handleRevoke}
                    onDelete={handleDelete}
                  />
                ))}
              </tbody>
            </table>
          </div>
        ) : !loading ? (
          <div className="workbench-muted mt-4 rounded-2xl border border-dashed workbench-border p-8 text-center">
            No users match this search.
          </div>
        ) : null}
      </section>
    </div>
  );
}
