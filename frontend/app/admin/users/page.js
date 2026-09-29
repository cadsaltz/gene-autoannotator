import AppShell from "../../../components/AppShell";
import UsersTable from "../../../components/admin/UsersTable";
import { requireAdminPage } from "../../../lib/session";

export const metadata = {
  title: "Users · Admin · Gene Autoannotator",
};

export default async function AdminUsersPage() {
  const admin = await requireAdminPage("/admin/users");
  return (
    <AppShell>
      <UsersTable currentUserId={admin?.id ?? null} />
    </AppShell>
  );
}
