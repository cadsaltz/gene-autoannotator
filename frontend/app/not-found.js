import Link from "next/link";

import AppShell from "../components/AppShell";

export const metadata = {
  title: "Page not found · Gene Autoannotator",
};

export default function NotFound() {
  return (
    <AppShell publicPage>
      <section className="mx-auto max-w-md">
        <div className="workbench-card p-7">
          <p className="workbench-kicker">404</p>
          <h1 className="workbench-foreground mt-2 text-3xl font-semibold tracking-tight">
            Page not found
          </h1>
          <p className="mt-4 text-sm workbench-muted">
            We couldn&apos;t find the page you were looking for. It may have moved, or the link
            may be mistyped.
          </p>
          <Link href="/" className="workbench-button workbench-button-primary mt-6 min-h-11 px-5">
            Back to home
          </Link>
        </div>
      </section>
    </AppShell>
  );
}
