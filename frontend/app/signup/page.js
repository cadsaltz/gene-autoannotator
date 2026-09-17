import { Suspense } from "react";

import AppShell from "../../components/AppShell";
import { SignupForm } from "../../components/AuthForms";

export const metadata = {
  title: "Sign up · Gene Autoannotator",
};

export default function SignupPage() {
  return (
    <AppShell>
      <Suspense fallback={<p className="workbench-muted text-sm">Loading…</p>}>
        <SignupForm />
      </Suspense>
    </AppShell>
  );
}
