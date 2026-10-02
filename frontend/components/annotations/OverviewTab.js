import { getGeneratedFieldRows, getTargetGoTerms } from "../../lib/annotationDisplay";
import { isBooleanValue, isNoData, planAnnotationGrid, splitListValue } from "../../lib/annotationLayout";
import { getAnnotationNotes, getQualityFlags, getSelectedPapers } from "../../lib/annotationSummary";
import { getCitedPmids } from "../../lib/citations";
import { CheckIcon, MinusIcon } from "../icons";
import CitedText from "./CitedText";
import PapersTable from "./PapersTable";
import { Badge, Card, CardHeader } from "./ui";

const TILE_SPAN = { full: "col-span-12", half: "col-span-12 xl:col-span-6" };
const PREVIEW_PAPER_COUNT = 4;

function CitesHint({ text }) {
  const count = getCitedPmids(text).length;
  if (count === 0) return null;
  return (
    <span className="shrink-0 text-xs text-fg-muted">
      Cites {count} paper{count === 1 ? "" : "s"}
    </span>
  );
}

function ProvenanceBadge({ row }) {
  if (!row.orthologDerived) return null;
  const source = row.orthologBlock?.sourceLabel;
  const prefix = row.orthologOnly ? "From ortholog" : "Target + ortholog";
  return (
    <Badge tone="warning" title={source || undefined}>
      {source ? `${prefix}: ${source}` : prefix}
    </Badge>
  );
}

function FieldTile({ tile }) {
  const { row, span, lead } = tile;
  return (
    <Card className={`${TILE_SPAN[span]} px-6 py-5`}>
      <CardHeader
        title={row.label}
        aside={
          <span className="flex min-w-0 items-center gap-2">
            <ProvenanceBadge row={row} />
            <CitesHint text={row.value} />
          </span>
        }
      />
      <p
        className={`mt-2.5 max-w-[110ch] whitespace-pre-wrap text-fg-secondary ${
          lead ? "text-base leading-[26px]" : "text-[15px] leading-6"
        }`}
      >
        <CitedText text={row.value} />
      </p>
    </Card>
  );
}

function CompactValue({ value }) {
  if (value === "True") {
    return (
      <span className="inline-flex items-center gap-1.5">
        <CheckIcon className="text-success-solid" />
        Yes
      </span>
    );
  }
  if (value === "False") {
    return (
      <span className="inline-flex items-center gap-1.5 text-fg-secondary">
        <MinusIcon className="text-fg-subtle" />
        No
      </span>
    );
  }
  if (isNoData(value)) {
    return <span className="font-normal text-fg-muted">{value}</span>;
  }
  return (
    <span className="flex flex-wrap gap-1.5">
      {splitListValue(value).map((item, index) => (
        <Badge key={`${item}-${index}`} tone="brand">
          {item}
        </Badge>
      ))}
    </span>
  );
}

function ClassificationCard({ rows }) {
  return (
    <Card className="px-6 py-5">
      <CardHeader title="Classification" />
      <dl className="mt-3 grid gap-3 text-sm">
        {rows.map((row) => (
          <div
            key={row.key}
            className={
              isBooleanValue(row.value) || isNoData(row.value)
                ? "flex items-center justify-between gap-4"
                : "grid gap-2"
            }
          >
            <dt className="text-fg-muted">{row.label}</dt>
            <dd className="font-medium text-fg">
              <CompactValue value={row.value} />
            </dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}

function GoTermsCard({ terms }) {
  return (
    <Card className="px-6 py-5">
      <CardHeader
        title="Gene Ontology"
        aside={
          <span className="text-xs text-fg-muted">
            {terms.length} term{terms.length === 1 ? "" : "s"}
          </span>
        }
      />
      <ul className="mt-2 divide-y divide-line text-sm">
        {terms.map((term, index) => (
          <li key={`${term.id}-${index}`} className="flex items-baseline justify-between gap-3 py-2">
            <span className="text-fg-secondary">{term.name}</span>
            <span className="shrink-0 font-mono text-xs text-fg-muted">{term.id}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function NotesCard({ notes, flags, className }) {
  return (
    <Card className={`${className} px-6 py-5`}>
      <CardHeader
        title="Annotation notes"
        aside={
          flags.length > 0 ? (
            <span className="flex flex-wrap justify-end gap-1.5">
              {flags.map((flag, index) => (
                <Badge key={`${flag}-${index}`} tone="warning" dot>
                  {flag}
                </Badge>
              ))}
            </span>
          ) : (
            <CitesHint text={notes} />
          )
        }
      />
      <p className="mt-2.5 max-w-[110ch] whitespace-pre-wrap text-[15px] leading-6 text-fg-secondary">
        <CitedText text={notes} />
      </p>
    </Card>
  );
}

export default function OverviewTab({ annotation, profileFields, onViewLiterature }) {
  const { tiles, compact } = planAnnotationGrid(getGeneratedFieldRows(annotation, profileFields));
  const goTerms = getTargetGoTerms(annotation);
  const notes = getAnnotationNotes(annotation);
  const flags = getQualityFlags(annotation);
  const papers = getSelectedPapers(annotation);
  const sideCards = [
    compact.length > 0 ? <ClassificationCard key="classification" rows={compact} /> : null,
    goTerms.length > 0 ? <GoTermsCard key="go" terms={goTerms} /> : null,
  ].filter(Boolean);

  return (
    <div className="grid grid-cols-12 gap-5">
      {tiles.map((tile) => (
        <FieldTile key={tile.row.key} tile={tile} />
      ))}

      {notes ? (
        <>
          <NotesCard
            notes={notes}
            flags={flags}
            className={sideCards.length > 0 ? "col-span-12 xl:col-span-8" : "col-span-12"}
          />
          {sideCards.length > 0 ? (
            <div className="col-span-12 flex flex-col gap-5 xl:col-span-4">{sideCards}</div>
          ) : null}
        </>
      ) : (
        sideCards.map((card) => (
          <div key={card.key} className={sideCards.length > 1 ? "col-span-12 xl:col-span-6" : "col-span-12"}>
            {card}
          </div>
        ))
      )}

      {papers.length > 0 ? (
        <Card className="col-span-12 overflow-hidden">
          <div className="px-6 pt-5">
            <CardHeader
              title="Selected papers"
              aside={
                papers.length > PREVIEW_PAPER_COUNT ? (
                  <button
                    type="button"
                    onClick={onViewLiterature}
                    className="text-sm font-semibold text-brand-fg hover:underline"
                  >
                    View all {papers.length} →
                  </button>
                ) : null
              }
            />
          </div>
          <PapersTable papers={papers.slice(0, PREVIEW_PAPER_COUNT)} className="mt-3" />
        </Card>
      ) : null}
    </div>
  );
}
