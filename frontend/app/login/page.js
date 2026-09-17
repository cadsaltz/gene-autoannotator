import { Suspense } from "react";

import AppShell from "../../components/AppShell";
import { LoginForm } from "../../components/AuthForms";

export const metadata = {
  title: "Sign in · Gene Autoannotator",
};

export default function LoginPage() {
  return (
    <AppShell>
      <Suspense fallback={<p className="workbench-muted text-sm">Loading…</p>}>
        <LoginForm />
      </Suspense>
    </AppShell>
  );
}
