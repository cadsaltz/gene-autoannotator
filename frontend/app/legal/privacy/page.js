import AppShell from "../../../components/AppShell";
import LegalPlaceholder from "../../../components/LegalPlaceholder";
import { LEGAL_DOCUMENTS } from "../../../lib/legal";

const legalDocument = LEGAL_DOCUMENTS["privacy"];

export const metadata = {
  title: `${legalDocument.title} · Gene Autoannotator`,
};

export default function PrivacyPage() {
  return (
    <AppShell>
      <LegalPlaceholder {...legalDocument} />
    </AppShell>
  );
}
