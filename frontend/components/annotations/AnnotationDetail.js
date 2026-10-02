"use client";

import { hasOrthologColumn } from "../../lib/annotationDisplay";
import { getSelectedPapers } from "../../lib/annotationSummary";
import { annotationViewForVersion, getTotalVersionCount } from "../../lib/annotationVersions";
import AnnotationHeader from "./AnnotationHeader";
import AnnotationTabs from "./AnnotationTabs";
import LiteratureTab from "./LiteratureTab";
import MetadataTab from "./MetadataTab";
import OrthologTab from "./OrthologTab";
import OverviewTab from "./OverviewTab";
import StatStrip from "./StatStrip";
import { Card } from "./ui";
import VersionsTab from "./VersionsTab";

function EmptyDetail() {
  return (
    <div className="grid min-h-80 place-items-center rounded-xl border border-dashed border-line-strong p-10 text-center">
      <div>
        <p className="text-base font-semibold text-fg">No annotation selected</p>
        <p className="mt-1 max-w-md text-sm text-fg-muted">
          Search by locus, gene name, or organism, then pick a result to read its annotation.
        </p>
      </div>
    </div>
  );
}

export default function AnnotationDetail({
  annotation,
  profileFields,
  versions,
  selectedVersionKey,
  onSelectVersion,
  onLoadVersions,
  isLoadingVersions,
  activeTab,
  onTabChange,
}) {
  if (!annotation) {
    return <EmptyDetail />;
  }

  const view = annotationViewForVersion(annotation, selectedVersionKey, versions);
  const totalVersions = getTotalVersionCount(annotation, versions);
  const paperCount = getSelectedPapers(view).length;
  const showOrtholog = hasOrthologColumn(view);
  const tabs = [
    { id: "annotation", label: "Annotation" },
    { id: "literature", label: "Literature", count: paperCount || undefined },
    { id: "versions", label: "Versions", count: totalVersions },
    ...(showOrtholog ? [{ id: "ortholog", label: "Ortholog" }] : []),
    { id: "metadata", label: "Metadata" },
    { id: "raw", label: "Raw JSON" },
  ];
  const current = tabs.some((tab) => tab.id === activeTab) ? activeTab : "annotation";

  function selectVersion(key) {
    onSelectVersion(key);
    onTabChange("annotation");
  }

  function selectHeaderVersion(key) {
    onSelectVersion(key);
    if (current !== activeTab) onTabChange(current);
  }

  return (
    <article className="mx-auto min-w-0 max-w-[105rem]">
      <AnnotationHeader
        annotation={annotation}
        view={view}
        versions={versions}
        selectedVersionKey={selectedVersionKey}
        onSelectVersion={selectHeaderVersion}
      />
      <StatStrip annotation={view} />
      <AnnotationTabs tabs={tabs} active={current} onChange={onTabChange} />
      <div
        role="tabpanel"
        id={`annotation-panel-${current}`}
        aria-labelledby={`annotation-tab-${current}`}
        tabIndex={0}
        className="mt-6 outline-none"
      >
        {current === "annotation" ? (
          <OverviewTab
            annotation={view}
            profileFields={profileFields}
            onViewLiterature={() => onTabChange("literature")}
          />
        ) : null}
        {current === "literature" ? <LiteratureTab annotation={view} /> : null}
        {current === "versions" ? (
          <VersionsTab
            annotation={annotation}
            versions={versions}
            selectedVersionKey={selectedVersionKey}
            onSelectVersion={selectVersion}
            onLoadVersions={onLoadVersions}
            isLoadingVersions={isLoadingVersions}
          />
        ) : null}
        {current === "ortholog" ? <OrthologTab annotation={view} profileFields={profileFields} /> : null}
        {current === "metadata" ? <MetadataTab annotation={view} /> : null}
        {current === "raw" ? (
          <Card className="overflow-hidden">
            <pre className="annotation-raw-json max-h-[70vh] p-5 font-mono text-xs leading-5 text-fg-secondary">
              {JSON.stringify(view.result, null, 2)}
            </pre>
          </Card>
        ) : null}
      </div>
    </article>
  );
}
