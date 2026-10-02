import { getStatCells } from "../../lib/annotationSummary";
import { Meter } from "./ui";

export default function StatStrip({ annotation }) {
  return (
    <dl className="mt-5 grid grid-cols-2 overflow-hidden rounded-xl border border-line bg-surface shadow-xs sm:grid-cols-3 xl:grid-cols-6">
      {getStatCells(annotation).map((cell) => (
        <div key={cell.key} title={cell.title} className="-mb-px -ml-px border-b border-l border-line px-4 py-3">
          <dt className="text-xs font-medium text-fg-muted">{cell.label}</dt>
          <dd className="mt-0.5 flex items-center gap-2 whitespace-nowrap font-semibold text-fg">
            {cell.value}
            {cell.detail ? <span className="text-xs font-normal text-fg-muted">{cell.detail}</span> : null}
            {cell.meter != null ? <Meter value={cell.meter} className="max-w-[72px]" /> : null}
          </dd>
        </div>
      ))}
    </dl>
  );
}
