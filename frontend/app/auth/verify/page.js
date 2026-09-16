import { Suspense } from "react";

import AppShell from "../../../components/AppShell";
import { VerifyForm } from "../../../components/AuthForms";

export const metadata = {
  title: "Verify · Gene Autoannotator",
};

export default function VerifyPage() {
  return (
    <AppShell>
      <Suspense
        fallback={
          <div className="workbench-card mx-auto max-w-md p-7 text-sm workbench-muted">
            Loading verification form…
          </div>
        }
      >
        <VerifyForm />
      </Suspense>
    </AppShell>
  );
}
