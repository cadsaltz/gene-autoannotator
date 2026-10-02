import { redirect } from "next/navigation";
import { Suspense } from "react";

import AnnotationExplorer from "../../components/AnnotationExplorer";
import AppShell from "../../components/AppShell";
import { searchStoredAnnotations } from "../../lib/annotationStore";
import { loadAnnotationsPage } from "../../lib/annotationsPage";
import { getAnnotationsCollection } from "../../lib/mongodb";
import { getServerSession } from "../../lib/session";

export const metadata = {
  title: "Annotations · Gene Autoannotator",
};

async function searchAnnotations(query) {
  const collection = await getAnnotationsCollection();
  return searchStoredAnnotations(collection, query);
}

export default async function AnnotationsPage({ searchParams }) {
  const params = await searchParams;
  const initialQuery = params?.query || "";
  const session = await getServerSession();
  const initial = await loadAnnotationsPage({
    session,
    query: initialQuery,
    search: searchAnnotations,
  });
  if (initial.redirectTo) {
    redirect(initial.redirectTo);
  }

  return (
    <AppShell fullWidth>
      <Suspense
        fallback={
          <div className="px-6 py-8 text-sm text-fg-muted">Loading annotation search…</div>
        }
      >
        <AnnotationExplorer
          initialQuery={initialQuery}
          initialMatches={initial.matches}
          initialMessage={initial.message}
        />
      </Suspense>
    </AppShell>
  );
}
