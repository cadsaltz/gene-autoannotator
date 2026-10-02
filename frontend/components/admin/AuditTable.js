"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  AUDIT_ACTIONS,
  formatAuditDetails,
  formatAuditTarget,
  formatLocalTime,
} from "../../lib/adminConsole";
import { adminAudit } from "../../lib/api";

export default function AuditTable({ initialAction = "", initialUserId = "" }) {
  const [action, setAction] = useState(initialAction);
  const [userId, setUserId] = useState(initialUserId);
  const [events, setEvents] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const loadSeq = useRef(0);

  const load = useCallback(async (filters) => {
    const seq = ++loadSeq.current;
    setLoading(true);
    try {
      const payload = await adminAudit({
        action: filters.action.trim(),
        user_id: filters.userId.trim(),
      });
      if (seq !== loadSeq.current) return;
      setEvents(payload.events || []);
      setError("");
    } catch (loadError) {
      if (seq === loadSeq.current) setError(loadError.message);
    } finally {
      if (seq === loadSeq.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    async function loadInitialData() {
      await load({ action: initialAction, userId: initialUserId });
    }

    loadInitialData();
  }, [load, initialAction, initialUserId]);

  function handleSubmit(event) {
    event.preventDefault();
    load({ action, userId });
  }

  function handleClear() {
    setAction("");
    setUserId("");
    load({ action: "", userId: "" });
  }

  function filterByUser(id) {
    setUserId(id);
    load({ action, userId: id });
  }

  return (
    <div className="grid gap-5">
      <section className="workbench-card p-6">
        <p className="workbench-kicker">Admin</p>
        <h1 className="workbench-foreground mt-2 text-3xl font-semibold tracking-tight">
          Audit log
        </h1>
        <p className="workbench-muted mt-3 max-w-2xl text-sm leading-6">
          Newest events first. Filtering by user matches events they performed or that targeted
          their account.
        </p>
        <form onSubmit={handleSubmit} className="mt-6 flex flex-wrap items-end gap-3">
          <label className="grid gap-1 text-sm">
            <span className="workbench-muted font-semibold">Action</span>
            <select
              value={action}
              onChange={(event) => setAction(event.target.value)}
              className="workbench-input"
            >
              <option value="">All actions</option>
              {AUDIT_ACTIONS.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
              {action && !AUDIT_ACTIONS.includes(action) ? (
                <option value={action}>{action}</option>
              ) : null}
            </select>
          </label>
          <label className="grid gap-1 text-sm">
            <span className="workbench-muted font-semibold">User ID</span>
            <input
              type="text"
              value={userId}
              onChange={(event) => setUserId(event.target.value)}
              placeholder="Any user"
              className="workbench-input w-72 font-mono text-xs"
            />
          </label>
          <button type="submit" className="workbench-button workbench-button-primary">
            Apply
          </button>
          <button
            type="button"
            onClick={handleClear}
            className="workbench-button workbench-button-secondary"
          >
            Clear
          </button>
        </form>
        {error ? (
          <p
            role="alert"
            className="workbench-amber-bg mt-4 rounded-xl border workbench-border p-4 text-sm text-warning-fg"
          >
            {error}
          </p>
        ) : null}
      </section>

      <section className="workbench-card p-6">
        <p className="workbench-muted text-sm">
          {loading
            ? "Loading events…"
            : `${events.length} event${events.length === 1 ? "" : "s"}`}
        </p>
        {events.length > 0 ? (
          <div className="mt-4 overflow-x-auto rounded-xl border workbench-border">
            <table className="min-w-full text-left text-sm">
              <thead className="workbench-muted-bg workbench-muted text-xs font-medium">
                <tr>
                  <th className="px-3 py-2">Time</th>
                  <th className="px-3 py-2">Actor</th>
                  <th className="px-3 py-2">Action</th>
                  <th className="px-3 py-2">Target</th>
                  <th className="px-3 py-2">Details</th>
                </tr>
              </thead>
              <tbody>
                {events.map((event) => (
                  <tr key={event.id} className="border-t workbench-border">
                    <td className="workbench-muted whitespace-nowrap px-3 py-2 align-top text-xs">
                      {formatLocalTime(event.created_at)}
                    </td>
                    <td className="px-3 py-2 align-top">
                      {event.actor_user_id ? (
                        <button
                          type="button"
                          onClick={() => filterByUser(event.actor_user_id)}
                          title="Show only this user's events"
                          className="workbench-foreground text-left font-semibold hover:underline"
                        >
                          {event.actor_email || event.actor_user_id}
                        </button>
                      ) : (
                        <span className="workbench-muted">anonymous</span>
                      )}
                      {event.ip ? (
                        <p className="workbench-muted font-mono text-xs">{event.ip}</p>
                      ) : null}
                    </td>
                    <td className="workbench-foreground px-3 py-2 align-top font-mono text-xs">
                      {event.action}
                    </td>
                    <td className="workbench-muted px-3 py-2 align-top font-mono text-xs">
                      {formatAuditTarget(event)}
                    </td>
                    <td className="workbench-muted max-w-md break-all px-3 py-2 align-top font-mono text-xs">
                      {formatAuditDetails(event.details)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : !loading ? (
          <div className="workbench-muted mt-4 rounded-xl border border-dashed workbench-border p-8 text-center">
            No audit events match these filters.
          </div>
        ) : null}
      </section>
    </div>
  );
}
