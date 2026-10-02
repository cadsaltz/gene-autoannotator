import { buildVersionOptions } from "../../lib/annotationVersions";
import { Badge, Card } from "./ui";

export default function VersionsTab({
  annotation,
  versions,
  selectedVersionKey,
  onSelectVersion,
  onLoadVersions,
  isLoadingVersions,
}) {
  const hasOlderVersions = (annotation.version_count || 0) > 0;

  if (hasOlderVersions && !versions) {
    return (
      <Card className="px-6 py-5">
        <p className="text-sm text-fg-muted">
          {isLoadingVersions ? "Loading version history…" : "Version history has not been loaded."}
        </p>
        {!isLoadingVersions ? (
          <button type="button" onClick={onLoadVersions} className="workbench-button workbench-button-secondary mt-4">
            Load version history
          </button>
        ) : null}
      </Card>
    );
  }

  return (
    <Card className="overflow-hidden">
      <ul className="divide-y divide-line">
        {buildVersionOptions(annotation, versions).map((option) => {
          const isSelected = option.key === selectedVersionKey;
          const generated = option.generated_at ? new Date(option.generated_at).toLocaleString() : "Unknown";
          return (
            <li key={option.key}>
              <button
                type="button"
                onClick={() => onSelectVersion(option.key)}
                aria-current={isSelected ? "true" : undefined}
                className={`flex w-full flex-wrap items-center gap-x-6 gap-y-1 px-6 py-4 text-left text-sm transition ${
                  isSelected ? "bg-brand-tint" : "hover:bg-surface-muted"
                }`}
              >
                <span className="flex min-w-40 items-center gap-2 font-semibold text-fg">
                  Version {option.versionNumber}
                  {option.isCurrent ? <Badge tone="brand">Latest</Badge> : null}
                </span>
                <span className="text-fg-secondary">
                  {option.gene_name || annotation.gene_name || annotation.normalized_locus}
                </span>
                <span className="text-fg-muted">
                  Generated {generated}
                  {option.job_id ? ` · job ${option.job_id}` : ""}
                </span>
                {isSelected ? <span className="ml-auto text-xs font-semibold text-brand-fg">Viewing</span> : null}
              </button>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
