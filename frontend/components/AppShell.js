"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { getMe, logout } from "../lib/authApi";
import { isNavItemActive, navItemsFor } from "../lib/navItems";
import { LogoMark, PlusIcon } from "./icons";
import SiteFooter from "./SiteFooter";
import ThemeToggle from "./ThemeToggle";

function SuspendedCard() {
  return (
    <section className="mx-auto max-w-md">
      <div className="workbench-card p-7">
        <p className="workbench-kicker">Account</p>
        <h1 className="workbench-foreground mt-2 text-3xl font-semibold tracking-tight">
          This account is suspended
        </h1>
        <p className="mt-4 text-sm workbench-muted">
          Contact the site administrators if you think this is a mistake.
        </p>
      </div>
    </section>
  );
}

function SessionLoading() {
  return (
    <p className="p-6 text-sm workbench-muted" role="status">
      Loading…
    </p>
  );
}

function initialsFor(user) {
  const source = String(user?.username || user?.email || "?").trim();
  return source.slice(0, 2).toUpperCase();
}

export default function AppShell({ children, publicPage = false, fullWidth = false }) {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState(null);
  const [suspended, setSuspended] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    getMe()
      .then((me) => {
        if (!cancelled) {
          setUser(me);
          setSuspended(false);
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setUser(null);
          setSuspended(error?.status === 403);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const signedIn = Boolean(user);
  const visibleNavItems = suspended ? navItemsFor(null).slice(0, 1) : navItemsFor(user);

  async function handleSignOut() {
    try {
      await logout();
    } catch {
      // Clear local state even if logout request fails.
    }
    setUser(null);
    setSuspended(false);
    router.push("/login");
    router.refresh();
  }

  return (
    <main className="workbench-app flex flex-col">
      <header className="sticky top-0 z-30 border-b border-line bg-surface">
        <div className="flex min-h-16 flex-wrap items-center gap-x-8 gap-y-2 px-4 py-3 sm:px-6 lg:px-8 lg:py-0">
          <Link href="/" className="flex items-center gap-2.5 text-base font-semibold text-fg">
            <LogoMark />
            Gene Autoannotator
          </Link>

          <nav aria-label="Main" className="flex flex-wrap gap-1">
            {visibleNavItems.map((item) => {
              const active = isNavItemActive(pathname, item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={`rounded-md px-3 py-2 text-sm font-semibold transition ${
                    active
                      ? "bg-surface-muted text-fg"
                      : "text-fg-muted hover:bg-surface-muted hover:text-fg-secondary"
                  }`}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>

          <div className="ml-auto flex items-center gap-3">
            <ThemeToggle />
            {signedIn ? (
              <Link
                href="/jobs"
                className="workbench-button workbench-button-secondary hidden sm:inline-flex"
              >
                <PlusIcon />
                New job
              </Link>
            ) : null}
            {signedIn || suspended ? (
              <div className="flex items-center gap-3">
                {signedIn ? (
                  <span
                    role="img"
                    aria-label={`Signed in as ${user.email}`}
                    title={user.email}
                    className="grid size-9 place-items-center rounded-full bg-brand-tint-strong text-sm font-semibold text-brand-fg"
                  >
                    {initialsFor(user)}
                  </span>
                ) : null}
                <button
                  type="button"
                  onClick={handleSignOut}
                  disabled={loading}
                  className="text-sm font-semibold text-fg-muted transition hover:text-fg disabled:opacity-60"
                >
                  Sign out
                </button>
              </div>
            ) : null}
          </div>
        </div>
      </header>

      <div className={fullWidth ? "w-full flex-1" : "mx-auto w-full max-w-7xl flex-1 px-6 py-8"}>
        {publicPage ? children : loading ? <SessionLoading /> : suspended ? <SuspendedCard /> : children}
      </div>
      <SiteFooter />
    </main>
  );
}
