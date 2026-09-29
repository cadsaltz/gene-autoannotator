import AppShell from "../../../components/AppShell";
import LegalPlaceholder from "../../../components/LegalPlaceholder";
import { LEGAL_DOCUMENTS } from "../../../lib/legal";

const legalDocument = LEGAL_DOCUMENTS["acceptable-use"];

export const metadata = {
  title: `${legalDocument.title} · Gene Autoannotator`,
};

export default function AcceptableUsePage() {
  return (
    <AppShell publicPage>
      <LegalPlaceholder {...legalDocument} />
    </AppShell>
  );
}
