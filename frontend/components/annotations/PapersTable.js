import { pmcUrl, pubmedUrl } from "../../lib/citations";
import { Badge, Meter } from "./ui";

export default function PapersTable({ papers, className = "" }) {
  return (
    <div className={`overflow-x-auto ${className}`}>
      <table className="w-full min-w-[640px] border-collapse text-sm">
        <thead>
          <tr className="border-y border-line bg-surface-muted text-left text-xs text-fg-muted">
            <th scope="col" className="px-6 py-2.5 font-medium">Title</th>
            <th scope="col" className="px-4 py-2.5 font-medium">Year</th>
            <th scope="col" className="px-4 py-2.5 font-medium">Relevance</th>
            <th scope="col" className="px-4 py-2.5 font-medium">Match</th>
            <th scope="col" className="px-6 py-2.5 font-medium">PMID</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {papers.map((paper) => (
            <tr key={paper.key}>
              <td className="w-3/5 max-w-0 px-6 py-3">
                {paper.pmcId ? (
                  <a
                    href={pmcUrl(paper.pmcId)}
                    target="_blank"
                    rel="noopener noreferrer"
                    title={paper.title}
                    className="block truncate font-medium text-fg hover:text-brand-fg"
                  >
                    {paper.title}
                  </a>
                ) : (
                  <span title={paper.title} className="block truncate font-medium text-fg">
                    {paper.title}
                  </span>
                )}
              </td>
              <td className="px-4 py-3 text-fg-tertiary">{paper.year ?? "—"}</td>
              <td className="px-4 py-3 text-fg-tertiary">
                {paper.score != null ? (
                  <span className="flex items-center gap-2.5">
                    <Meter value={paper.score} className="max-w-24" />
                    {paper.score.toFixed(2)}
                  </span>
                ) : (
                  "—"
                )}
              </td>
              <td className="px-4 py-3">
                {paper.match ? <Badge tone={paper.match.tone}>{paper.match.label}</Badge> : "—"}
              </td>
              <td className="px-6 py-3 font-mono text-fg-tertiary">
                {paper.pmid ? (
                  <a
                    href={pubmedUrl(paper.pmid)}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="hover:text-brand-fg"
                  >
                    {paper.pmid}
                  </a>
                ) : (
                  "—"
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
