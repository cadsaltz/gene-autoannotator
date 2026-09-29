import { Suspense } from "react";
import { redirect } from "next/navigation";

import AppShell from "../../components/AppShell";
import JobWorkspace from "../../components/JobWorkspace";
import UserJobsWorkspace from "../../components/UserJobsWorkspace";
import { getServerSession } from "../../lib/session";

export const metadata = {
  title: "Jobs · Gene Autoannotator",
};

export default async function JobsPage() {
  const { user, reason } = await getServerSession();
  if (!user && reason === "signed_out") {
    redirect("/login?next=/jobs");
  }

  return (
    <AppShell>
      <Suspense
        fallback={
          <div className="rounded-3xl border border-white/10 bg-slate-900 p-8 text-slate-300">
            Loading job workspace...
          </div>
        }
      >
        {user?.role === "admin" ? <JobWorkspace /> : <UserJobsWorkspace />}
      </Suspense>
    </AppShell>
  );
}
