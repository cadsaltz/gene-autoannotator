import AppShell from "../../components/AppShell";
import { LoginForm } from "../../components/AuthForms";

export const metadata = {
  title: "Sign in · Gene Autoannotator",
};

export default function LoginPage() {
  return (
    <AppShell>
      <LoginForm />
    </AppShell>
  );
}
