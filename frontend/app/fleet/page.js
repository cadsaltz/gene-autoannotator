import AppShell from "../../components/AppShell";
import FleetDashboard from "../../components/FleetDashboard";
import { requireAdminPage } from "../../lib/session";

export default async function FleetPage() {
  await requireAdminPage("/fleet");
  return (
    <AppShell>
      <FleetDashboard />
    </AppShell>
  );
}
