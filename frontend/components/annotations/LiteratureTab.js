import { getPmcIdsAnalyzed } from "../../lib/annotationDisplay";
import { getSelectedPapers } from "../../lib/annotationSummary";
import { pmcUrl } from "../../lib/citations";
import PapersTable from "./PapersTable";
import { Card, CardHeader } from "./ui";

export default function LiteratureTab({ annotation }) {
  const papers = getSelectedPapers(annotation);
  const pmcIds = getPmcIdsAnalyzed(annotation);

  return (
    <div className="grid gap-5">
      <Card className="overflow-hidden">
        <div className="px-6 pt-5">
          <CardHeader title="Selected papers" aside={<span className="text-xs text-fg-muted">Ranked by relevance</span>} />
        </div>
        {papers.length > 0 ? (
          <PapersTable papers={papers} className="mt-3" />
        ) : (
          <p className="px-6 pt-2 pb-5 text-sm text-fg-muted">No paper summaries were stored with this annotation.</p>
        )}
      </Card>

      <Card className="px-6 py-5">
        <CardHeader title="PMC IDs analyzed" aside={<span className="text-xs text-fg-muted">{pmcIds.length}</span>} />
        {pmcIds.length > 0 ? (
          <ul className="mt-3 flex flex-wrap gap-2">
            {pmcIds.map((pmcId) => (
              <li key={pmcId}>
                <a
                  href={pmcUrl(pmcId)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-block rounded-md border border-line bg-surface-muted px-2 py-0.5 font-mono text-xs text-fg-secondary transition hover:border-brand-line hover:text-brand-fg"
                >
                  PMC{pmcId}
                </a>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-sm text-fg-muted">No analyzed PMC IDs stored.</p>
        )}
      </Card>
    </div>
  );
}
