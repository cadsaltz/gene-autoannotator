import AppShell from "../../components/AppShell";
import { SignupForm } from "../../components/AuthForms";

export const metadata = {
  title: "Sign up · Gene Autoannotator",
};

export default function SignupPage() {
  return (
    <AppShell>
      <SignupForm />
    </AppShell>
  );
}
