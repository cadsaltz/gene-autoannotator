import { redirect } from "next/navigation";

import AppShell from "../../components/AppShell";
import ProfileWorkspace from "../../components/ProfileWorkspace";
import { getServerSession } from "../../lib/session";

export const metadata = {
  title: "Profiles · Gene Autoannotator",
};

export default async function ProfilesPage() {
  const { user, reason } = await getServerSession();
  if (!user && reason === "signed_out") {
    redirect("/login?next=/profiles");
  }

  return (
    <AppShell>
      <ProfileWorkspace canEdit={user?.role === "admin"} />
    </AppShell>
  );
}
