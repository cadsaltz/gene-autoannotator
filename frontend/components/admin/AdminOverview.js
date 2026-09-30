"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { formatQuotaLimit } from "../../lib/adminConsole";
import { adminOverview } from "../../lib/api";

const QUOTA_ROWS = [
  { key: "max_queued", label: "Global queued jobs" },
  { key: "user_max_active", label: "Active jobs per user" },
  { key: "user_max_per_day", label: "Jobs per user per 24 h" },
  { key: "user_max_batch", label: "Batch size per user" },
  { key: "ip_signups_per_day", label: "Signups per IP per day" },
  { key: "ip_logins_per_hour", label: "Logins per IP per hour" },
  { key: "ip_submits_per_hour", label: "Submissions per IP per hour" },
  { key: "ip_validations_per_hour", label: "Gene lookups per IP per hour" },
  { key: "otp_sends_per_email_per_hour", label: "Login codes per email per hour" },
];

const LINKS = [
  { href: "/admin/users", label: "Users", detail: "Roles, suspensions, quota overrides" },
  { href: "/admin/audit", label: "Audit log", detail: "Sign-ins, submissions, admin changes" },
  { href: "/jobs", label: "Jobs", detail: "Full queue with every user's jobs" },
  { href: "/fleet", label: "Fleet & health", detail: "Workers, stores, capacity" },
];

function Stat({ label, value, warn = false }) {
  return (
    <div
      className={`workbench-surface-bg rounded-2xl border workbench-border p-4 ${
        warn ? "health-status-warn" : "health-status-ok"
      }`}
    >
      <p className="workbench-muted text-sm font-semibold">{label}</p>
      <p className="workbench-foreground mt-2 text-2xl font-bold">{value ?? "—"}</p>
    </div>
  );
}

export default function AdminOverview() {
  const [overview, setOverview] = useState(null);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      setOverview(await adminOverview());
      setError("");
    } catch (loadError) {
      setError(loadError.message);
    }
  }, []);

  useEffect(() => {
    async function loadInitialData() {
      await refresh();
    }

    loadInitialData();
  }, [refresh]);

  const quotas = overview?.quota_config;

  return (
    <div className="grid gap-5">
      <section className="workbench-card p-6">
        <p className="workbench-kicker">Admin</p>
        <h1 className="workbench-foreground mt-2 text-3xl font-bold tracking-[-0.04em]">
          Admin console
        </h1>
        <p className="workbench-muted mt-3 max-w-2xl text-sm leading-6">
          Queue, worker, and account totals at a glance. Completed and failed counts cover the
          last 24 hours.
          {overview?.version ? ` Backend version ${overview.version}.` : ""}
        </p>
        <div className="mt-6">
          <button
            type="button"
            onClick={refresh}
            className="workbench-button workbench-button-secondary"
          >
            Refresh
          </button>
        </div>
        {error ? (
          <p
            role="alert"
            className="workbench-amber-bg mt-4 rounded-xl border workbench-border p-4 text-sm text-[#5f4b2e]"
          >
            {error}
          </p>
        ) : null}
      </section>

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="Queued" value={overview?.queued} />
        <Stat label="Running" value={overview?.running} />
        <Stat label="Completed (24 h)" value={overview?.completed_24h} />
        <Stat label="Failed (24 h)" value={overview?.failed_24h} warn={overview?.failed_24h > 0} />
        <Stat
          label="Workers online"
          value={overview?.workers_online}
          warn={overview ? overview.workers_online === 0 : false}
        />
        <Stat label="Users" value={overview?.users_total} />
        <Stat
          label="Suspended users"
          value={overview?.users_suspended}
          warn={overview?.users_suspended > 0}
        />
      </section>

      <div className="grid gap-5 lg:grid-cols-2">
        <section className="workbench-card p-6">
          <h2 className="workbench-foreground text-2xl font-bold tracking-[-0.03em]">
            Quota configuration
          </h2>
          <p className="workbench-muted mt-2 text-sm">
            Defaults from the backend environment. Per-user overrides are set on the Users page;
            0 means unlimited. Admins are never limited by per-user quotas.
          </p>
          <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
            {QUOTA_ROWS.map((row) => (
              <div key={row.key} className="border-t workbench-border pt-2">
                <dt className="workbench-muted text-xs font-bold uppercase tracking-[0.1em]">
                  {row.label}
                </dt>
                <dd className="workbench-foreground mt-1 font-semibold">
                  {formatQuotaLimit(quotas?.[row.key])}
                </dd>
              </div>
            ))}
          </dl>
        </section>

        <section className="workbench-card p-6">
          <h2 className="workbench-foreground text-2xl font-bold tracking-[-0.03em]">Manage</h2>
          <ul className="mt-4 grid gap-3">
            {LINKS.map((link) => (
              <li key={link.href}>
                <Link
                  href={link.href}
                  className="workbench-surface-bg block rounded-2xl border workbench-border p-4 transition hover:underline"
                >
                  <p className="workbench-foreground font-bold">{link.label}</p>
                  <p className="workbench-muted mt-1 text-sm">{link.detail}</p>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}
