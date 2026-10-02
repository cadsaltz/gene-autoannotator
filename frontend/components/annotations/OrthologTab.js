import { formatGoTermLabel, getGeneratedFieldRows, getOrthologGoTerms } from "../../lib/annotationDisplay";
import CitedText from "./CitedText";
import { Card, CardHeader } from "./ui";

export default function OrthologTab({ annotation, profileFields }) {
  const rows = getGeneratedFieldRows(annotation, profileFields).filter((row) => row.orthologDerived);
  const goTerms = getOrthologGoTerms(annotation);

  if (rows.length === 0 && goTerms.length === 0) {
    return (
      <Card className="px-6 py-5">
        <p className="text-sm text-fg-muted">No ortholog evidence was stored with this annotation.</p>
      </Card>
    );
  }

  return (
    <div className="grid gap-5">
      {rows.length > 0 ? (
        <Card className="overflow-hidden">
          <div className="px-6 pt-5">
            <CardHeader title="Target and ortholog evidence" />
          </div>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[720px] border-collapse text-sm">
              <thead>
                <tr className="border-y border-line bg-surface-muted text-left text-xs text-fg-muted">
                  <th scope="col" className="w-48 px-6 py-2.5 font-medium">Field</th>
                  <th scope="col" className="px-4 py-2.5 font-medium">Target</th>
                  <th scope="col" className="px-6 py-2.5 font-medium">Ortholog</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line align-top">
                {rows.map((row) => (
                  <tr key={row.key}>
                    <th scope="row" className="px-6 py-4 text-left font-semibold text-fg">
                      {row.label}
                    </th>
                    <td className="px-4 py-4 leading-6 text-fg-secondary">
                      {row.orthologOnly ? (
                        <span className="text-fg-muted">No target data</span>
                      ) : (
                        <CitedText text={row.value} />
                      )}
                    </td>
                    <td className="px-6 py-4 leading-6 text-fg-secondary">
                      <CitedText text={row.orthologOnly ? row.value : row.orthologBlock?.value || "No supported data"} />
                      {row.orthologBlock?.sourceLabel ? (
                        <p className="mt-2 text-xs font-medium text-warning-fg">From {row.orthologBlock.sourceLabel}</p>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ) : null}

      {goTerms.length > 0 ? (
        <Card className="px-6 py-5">
          <CardHeader title="Ortholog Gene Ontology terms" />
          <ul className="mt-2 divide-y divide-line text-sm text-fg-secondary">
            {goTerms.map((term, index) => (
              <li key={`${term.id}-${index}`} className="py-2">
                {formatGoTermLabel(term)}
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
    </div>
  );
}
