import { getMetadataRows } from "../../lib/annotationDisplay";
import { Card } from "./ui";

function Item({ label, mono = false, children }) {
  return (
    <div className="min-w-0">
      <dt className="text-fg-muted">{label}</dt>
      <dd className={`mt-1 whitespace-pre-wrap break-words text-fg ${mono ? "font-mono" : "font-medium"}`}>
        {children}
      </dd>
    </div>
  );
}

export default function MetadataTab({ annotation }) {
  const rows = getMetadataRows(annotation).filter((row) => row.key !== "annotation_notes");
  return (
    <Card className="px-6 py-5">
      <dl className="grid gap-x-8 gap-y-5 text-sm sm:grid-cols-2 xl:grid-cols-3">
        {annotation.job_id ? (
          <Item label="Job" mono>
            {annotation.job_id}
          </Item>
        ) : null}
        {annotation.profile_id ? (
          <Item label="Profile" mono>
            {annotation.profile_id}
          </Item>
        ) : null}
        {rows.map((row) => (
          <Item key={row.key} label={row.label}>
            {row.value}
          </Item>
        ))}
      </dl>
    </Card>
  );
}
