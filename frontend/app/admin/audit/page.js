import AppShell from "../../../components/AppShell";
import AuditTable from "../../../components/admin/AuditTable";
import { requireAdminPage } from "../../../lib/session";

export const metadata = {
  title: "Audit log · Admin · Gene Autoannotator",
};

export default async function AdminAuditPage({ searchParams }) {
  await requireAdminPage("/admin/audit");
  const params = await searchParams;
  return (
    <AppShell>
      <AuditTable
        initialAction={typeof params?.action === "string" ? params.action : ""}
        initialUserId={typeof params?.user_id === "string" ? params.user_id : ""}
      />
    </AppShell>
  );
}
