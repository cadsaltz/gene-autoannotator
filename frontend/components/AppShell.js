"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { getMe, logout } from "../lib/authApi";

const navItems = [
  { href: "/", label: "Guide" },
  { href: "/jobs", label: "Jobs" },
  { href: "/fleet", label: "Fleet & Health" },
  { href: "/profiles", label: "Profiles" },
  { href: "/annotations", label: "Annotations" },
];

const guestNavItems = [
  { href: "/", label: "Guide" },
  { href: "/login", label: "Sign in" },
  { href: "/signup", label: "Sign up" },
];

export default function AppShell({ children }) {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    getMe()
      .then((me) => {
        if (!cancelled) {
          setUser(me);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setUser(null);
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
  const visibleNavItems = signedIn ? navItems : guestNavItems;

  async function handleSignOut() {
    try {
      await logout();
    } catch {
      // Clear local state even if logout request fails.
    }
    setUser(null);
    router.push("/login");
    router.refresh();
  }

  return (
    <main className="workbench-app">
      <header className="workbench-nav">
        <div className="mx-auto flex max-w-7xl flex-col gap-4 px-6 py-5 sm:flex-row sm:items-center sm:justify-between">
          <Link href="/" className="group">
            <p className="text-sm font-bold uppercase tracking-[0.08em] text-[#f5f0e6]">
              Gene Autoannotator
            </p>
            <p className="workbench-nav-subtitle mt-1 text-sm">
              Web queue for long-running annotation jobs
            </p>
          </Link>

          <div className="flex flex-wrap items-center gap-3">
            <nav className="flex flex-wrap gap-2">
              {visibleNavItems.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`rounded-full border px-4 py-2 text-sm font-semibold transition ${
                    pathname === item.href
                      ? "workbench-nav-link-active"
                      : "workbench-nav-link"
                  }`}
                >
                  {item.label}
                </Link>
              ))}
            </nav>

            {signedIn ? (
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm text-[#f5f0e6]">{user.email}</span>
                <button
                  type="button"
                  onClick={handleSignOut}
                  className="rounded-full border px-4 py-2 text-sm font-semibold transition workbench-nav-link"
                  disabled={loading}
                >
                  Sign out
                </button>
              </div>
            ) : null}
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-7xl px-6 py-8">{children}</div>
    </main>
  );
}
