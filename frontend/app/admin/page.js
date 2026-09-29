import AppShell from "../../components/AppShell";
import AdminOverview from "../../components/admin/AdminOverview";
import { requireAdminPage } from "../../lib/session";

export const metadata = {
  title: "Admin · Gene Autoannotator",
};

export default async function AdminPage() {
  await requireAdminPage("/admin");
  return (
    <AppShell>
      <AdminOverview />
    </AppShell>
  );
}
