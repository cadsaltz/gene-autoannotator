"use client";

import { useState } from "react";
import Link from "next/link";

import {
  getAnnotation,
  getAnnotationVersions,
  getProfile,
  searchAnnotations,
} from "../lib/api";
import {
  getHiddenMatchCount,
  getVisibleMatches,
} from "../lib/annotationMatches";
import {
  getGeneratedFieldRows,
  getMetadataRows,
  getPmcIdsAnalyzed,
} from "../lib/annotationDisplay";
import {
  annotationViewForVersion,
  buildVersionOptions,
  CURRENT_VERSION_KEY,
  formatVersionLabel,
  getTotalVersionCount,
} from "../lib/annotationVersions";
import { buildJobPrefillHref } from "../lib/form";
import { resolveProfileFieldsForDisplay } from "../lib/profileStore";

function EmptyState({ query }) {
  const href = `/jobs?locus=${encodeURIComponent(query)}`;
  return (
    <div className="workbench-muted-bg rounded-2xl border border-dashed workbench-border p-8 text-center">
      <h2 className="workbench-foreground text-2xl font-bold tracking-[-0.03em]">No annotation found</h2>
      <p className="workbench-muted mx-auto mt-3 max-w-2xl text-sm leading-6">
        There is no stored annotation matching this search yet. You can submit
        the locus as a new queued job and return here after it completes.
      </p>
      <Link
        href={href}
        className="workbench-button workbench-button-primary mt-5"
      >
        Submit this gene for annotation
      </Link>
    </div>
  );
}

function AnnotationContent({ annotation, profileFields }) {
  const generatedRows = getGeneratedFieldRows(annotation, profileFields);
  const metadataRows = getMetadataRows(annotation);
  const pmcIdsAnalyzed = getPmcIdsAnalyzed(annotation);

  return (
    <div className="grid gap-4">
      <section className="rounded-xl border workbench-border bg-[#fffefa] p-5">
        <h3 className="workbench-foreground text-xl font-bold tracking-[-0.02em]">
          Generated annotation fields
        </h3>
        <dl className="mt-5 grid gap-4">
          {generatedRows.map((row) => (
            <div
              key={row.key}
              className={`rounded-xl border p-4 ${
                row.orthologDerived
                  ? "workbench-amber-bg border-[#d4c4a0]"
                  : "workbench-muted-bg workbench-border"
              }`}
            >
              <div className="flex flex-wrap items-center gap-2">
                <dt className="workbench-muted text-xs font-bold uppercase tracking-[0.1em]">
                  {row.label}
                </dt>
                {row.orthologDerived ? (
                  <span className="rounded-full border border-[#d4c4a0] bg-white/60 px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.08em] text-[#8a7340]">
                    Ortholog derived
                  </span>
                ) : null}
              </div>
              <dd className="mt-2 whitespace-pre-wrap text-sm leading-6 text-[#3d463f]">
                {row.value}
              </dd>
              {row.orthologBlock ? (
                <div className="mt-3 rounded-lg border border-[#d4c4a0] bg-white/60 p-3">
                  <p className="text-[10px] font-bold uppercase tracking-[0.08em] text-[#8a7340]">
                    From ortholog: {row.orthologBlock.sourceLabel}
                  </p>
                  {row.orthologBlock.value ? (
                    <p className="mt-1 whitespace-pre-wrap text-sm leading-6 text-[#3d463f]">
                      {row.orthologBlock.value}
                    </p>
                  ) : null}
                </div>
              ) : null}
            </div>
          ))}
        </dl>
      </section>

      <details className="rounded-xl border workbench-border bg-[#fffefa] p-4">
        <summary className="workbench-foreground cursor-pointer text-sm font-bold">
          Annotation metadata
        </summary>
        <dl className="mt-4 grid gap-3 text-sm">
          {metadataRows.map((row) => (
            <div key={row.key} className="workbench-muted-bg rounded-xl border workbench-border p-4">
              <dt className="workbench-muted text-xs font-bold uppercase tracking-[0.1em]">
                {row.label}
              </dt>
              <dd className="mt-2 whitespace-pre-wrap leading-6 text-[#3d463f]">{row.value}</dd>
            </div>
          ))}
        </dl>

        <details className="workbench-muted-bg mt-4 rounded-xl border workbench-border p-4">
          <summary className="workbench-foreground cursor-pointer text-sm font-bold">
            PMC IDs analyzed
          </summary>
          {pmcIdsAnalyzed.length > 0 ? (
            <ul className="mt-3 grid gap-2 text-sm text-[#3d463f] sm:grid-cols-2">
              {pmcIdsAnalyzed.map((pmcId) => (
                <li key={pmcId} className="rounded-lg bg-white/70 px-3 py-2">
                  PMC{pmcId}
                </li>
              ))}
            </ul>
          ) : (
            <p className="workbench-muted mt-3 text-sm">No analyzed PMC IDs stored.</p>
          )}
        </details>
      </details>

      <details className="min-w-0 max-w-full overflow-hidden rounded-xl border workbench-border bg-[#fffefa] p-4">
        <summary className="workbench-foreground cursor-pointer text-sm font-bold">
          Raw JSON
        </summary>
        <pre className="annotation-raw-json workbench-muted-bg mt-4 max-h-96 rounded-xl p-4 text-xs leading-5 text-[#3d463f]">
          {JSON.stringify(annotation.result, null, 2)}
        </pre>
      </details>
    </div>
  );
}

function VersionHistory({
  annotation,
  versions,
  selectedVersionKey,
  onSelectVersion,
  onLoadVersions,
  isLoadingVersions,
}) {
  const hasOlderVersions = (annotation.version_count || 0) > 0;
  const versionOptions = versions ? buildVersionOptions(annotation, versions) : [];
  const totalVersions = getTotalVersionCount(annotation, versions);

  if (!hasOlderVersions && !versions) {
    return null;
  }

  return (
    <section className="mt-6 rounded-xl border workbench-border bg-[#fffefa] p-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h3 className="workbench-foreground text-lg font-bold tracking-[-0.02em]">
            Version history
          </h3>
          <p className="workbench-muted mt-1 text-sm">
            {totalVersions} saved version{totalVersions === 1 ? "" : "s"}. Select one to review
            its generated fields and metadata.
          </p>
        </div>
        {hasOlderVersions && !versions && !isLoadingVersions ? (
          <button
            type="button"
            onClick={onLoadVersions}
            className="workbench-button workbench-button-secondary"
          >
            Load version history
          </button>
        ) : null}
      </div>

      {hasOlderVersions && !versions && isLoadingVersions ? (
        <p className="workbench-muted mt-4 text-sm">Loading version history...</p>
      ) : null}

      {versions ? (
        <div className="mt-4 grid gap-2">
          {versionOptions.map((option) => {
            const isSelected = selectedVersionKey === option.key;
            const generated = option.generated_at
              ? new Date(option.generated_at).toLocaleString()
              : "Unknown";

            return (
              <button
                type="button"
                key={option.key}
                onClick={() => onSelectVersion(option.key)}
                className={`rounded-xl border p-4 text-left text-sm transition ${
                  isSelected
                    ? "border-[#557864] bg-[#eef4ef]"
                    : "workbench-border workbench-muted-bg hover:border-[#557864]"
                }`}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="workbench-foreground font-bold">
                    {formatVersionLabel(option)}
                  </span>
                  {option.isCurrent ? (
                    <span className="rounded-full bg-[#557864] px-2 py-0.5 text-xs font-bold uppercase tracking-[0.08em] text-white">
                      Latest
                    </span>
                  ) : null}
                </div>
                <p className="workbench-muted mt-1">
                  {option.gene_name || annotation.gene_name || annotation.normalized_locus}
                </p>
                <p className="workbench-muted mt-1">
                  Generated {generated} · job {option.job_id || "Unknown"}
                </p>
              </button>
            );
          })}
        </div>
      ) : null}
    </section>
  );
}

function AnnotationDetail({
  annotation,
  profileFields,
  versions,
  selectedVersionKey,
  onSelectVersion,
  onLoadVersions,
  isLoadingVersions,
}) {
  if (!annotation) {
    return (
      <div className="workbench-card workbench-muted p-8">
        Select a search result to view the generated annotation.
      </div>
    );
  }

  const displayAnnotation = annotationViewForVersion(annotation, selectedVersionKey, versions);
  const selectedOption = buildVersionOptions(annotation, versions).find(
    (option) => option.key === selectedVersionKey,
  );
  const viewingHistorical = selectedVersionKey !== CURRENT_VERSION_KEY;
  const generated = displayAnnotation.generated_at
    ? new Date(displayAnnotation.generated_at).toLocaleString()
    : "Unknown";
  const totalVersions = getTotalVersionCount(annotation, versions);

  return (
    <article className="workbench-card min-w-0 max-w-full overflow-hidden p-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="workbench-kicker">
            {viewingHistorical ? "Historical annotation" : "Current annotation"}
          </p>
          <h2 className="workbench-foreground mt-2 text-3xl font-bold tracking-[-0.04em]">
            {displayAnnotation.gene_name || annotation.normalized_locus}
          </h2>
          <p className="workbench-muted mt-2 text-sm">
            {annotation.canonical_name} · {annotation.normalized_locus}
          </p>
          {selectedOption ? (
            <p className="workbench-muted mt-2 text-sm">
              Viewing {formatVersionLabel(selectedOption)}
            </p>
          ) : null}
        </div>
        {!viewingHistorical ? (
          <Link
            href={buildJobPrefillHref(annotation)}
            className="workbench-button workbench-button-secondary"
          >
            Update annotation
          </Link>
        ) : null}
      </div>

      {viewingHistorical ? (
        <p className="workbench-amber mt-4 rounded-xl border workbench-border px-4 py-3 text-sm">
          You are viewing an older saved version. Switch back to the latest version to see the
          current annotation or queue a new run.
        </p>
      ) : null}

      <dl className="mt-6 grid overflow-hidden rounded-xl border workbench-border text-sm sm:grid-cols-3">
        <div className="workbench-muted-bg border-b workbench-border p-4 sm:border-r sm:border-b-0">
          <dt className="workbench-muted text-xs font-bold uppercase tracking-[0.1em]">Generated</dt>
          <dd className="mt-1 text-[#3d463f]">{generated}</dd>
        </div>
        <div className="workbench-muted-bg border-b workbench-border p-4 sm:border-r sm:border-b-0">
          <dt className="workbench-muted text-xs font-bold uppercase tracking-[0.1em]">Versions</dt>
          <dd className="mt-1 text-[#3d463f]">{totalVersions}</dd>
        </div>
        <div className="workbench-muted-bg p-4">
          <dt className="workbench-muted text-xs font-bold uppercase tracking-[0.1em]">Job</dt>
          <dd className="mt-1 break-all text-[#3d463f]">{displayAnnotation.job_id || "Unknown"}</dd>
        </div>
      </dl>

      <VersionHistory
        annotation={annotation}
        versions={versions}
        selectedVersionKey={selectedVersionKey}
        onSelectVersion={onSelectVersion}
        onLoadVersions={onLoadVersions}
        isLoadingVersions={isLoadingVersions}
      />

      <div className="mt-6">
        <AnnotationContent annotation={displayAnnotation} profileFields={profileFields} />
      </div>
    </article>
  );
}

export default function AnnotationExplorer({
  initialQuery = "",
  initialMatches = [],
  initialMessage = "",
}) {
  const [query, setQuery] = useState(initialQuery);
  const [matches, setMatches] = useState(initialMatches);
  const [selected, setSelected] = useState(null);
  const [profileFields, setProfileFields] = useState(null);
  const [versions, setVersions] = useState(null);
  const [selectedVersionKey, setSelectedVersionKey] = useState(CURRENT_VERSION_KEY);
  const [isLoadingVersions, setIsLoadingVersions] = useState(false);
  const [message, setMessage] = useState(initialMessage);
  const [searchedQuery, setSearchedQuery] = useState(initialQuery);
  const [isSearching, setIsSearching] = useState(false);
  const [showAllMatches, setShowAllMatches] = useState(false);
  const hiddenMatchCount = getHiddenMatchCount(matches);
  const visibleMatches = getVisibleMatches(matches, showAllMatches);

  async function fetchVersions(annotationId) {
    setIsLoadingVersions(true);
    try {
      const payload = await getAnnotationVersions(annotationId);
      setVersions(payload.versions || []);
    } catch (error) {
      setMessage(error.message);
    } finally {
      setIsLoadingVersions(false);
    }
  }

  async function runSearch(nextQuery = query) {
    const trimmed = nextQuery.trim();
    if (!trimmed) {
      setMessage("Enter a locus, gene name, or organism-related term.");
      return;
    }

    setIsSearching(true);
    setMessage("");
    setSelected(null);
    setProfileFields(null);
    setVersions(null);
    setSelectedVersionKey(CURRENT_VERSION_KEY);
    setSearchedQuery(trimmed);
    setShowAllMatches(false);

    try {
      const payload = await searchAnnotations(trimmed);
      setMatches(payload.matches || []);
    } catch (error) {
      setMatches([]);
      setMessage(error.message);
    } finally {
      setIsSearching(false);
    }
  }

  async function loadAnnotation(annotationId) {
    setMessage("");
    setVersions(null);
    setProfileFields(null);
    setSelectedVersionKey(CURRENT_VERSION_KEY);

    try {
      const annotation = await getAnnotation(annotationId);
      setSelected(annotation);
      if (annotation.profile_id) {
        try {
          const profile = await getProfile(annotation.profile_id);
          setProfileFields(resolveProfileFieldsForDisplay(profile));
        } catch {
          // Fall back to the hard-coded field list when the profile is unavailable.
          setProfileFields(null);
        }
      }
      if ((annotation.version_count || 0) > 0) {
        await fetchVersions(annotationId);
      }
    } catch (error) {
      setMessage(error.message);
    }
  }

  async function loadVersions() {
    if (!selected) return;
    await fetchVersions(selected.id);
  }

  return (
    <div className="grid gap-5">
      <section className="workbench-card p-6">
        <p className="workbench-kicker">
          Annotation library
        </p>
        <h1 className="workbench-foreground mt-2 text-3xl font-bold tracking-[-0.04em]">
          Search generated annotations
        </h1>
        <p className="workbench-muted mt-3 max-w-3xl text-sm leading-6">
          Search by locus, gene name, profile, or terms present in stored
          annotation metadata. The latest version opens by default; select an
          older version to review its saved fields and metadata.
        </p>

        <form
          className="mt-6 flex flex-col gap-3 sm:flex-row"
          onSubmit={(event) => {
            event.preventDefault();
            runSearch();
          }}
        >
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="workbench-input min-w-0 flex-1"
            placeholder="Rv0001, dnaA, TcCLB.503799.4..."
          />
          <button
            type="submit"
            disabled={isSearching}
            className="workbench-button workbench-button-primary min-h-11 px-5 disabled:opacity-60"
          >
            {isSearching ? "Searching..." : "Search"}
          </button>
        </form>
        {message ? <p className="workbench-amber mt-4 text-sm">{message}</p> : null}
      </section>

      <div className="grid items-start gap-5 lg:grid-cols-[0.8fr_1.2fr]">
        <section className="workbench-card p-6">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <h2 className="workbench-foreground text-2xl font-bold tracking-[-0.03em]">
              Matches
            </h2>
            {hiddenMatchCount > 0 ? (
              <button
                type="button"
                onClick={() => setShowAllMatches((current) => !current)}
                className="workbench-button workbench-button-secondary w-36 shrink-0"
              >
                {showAllMatches ? "Hide all" : `View all (${matches.length})`}
              </button>
            ) : null}
          </div>
          <div className="mt-5 grid gap-3">
            {visibleMatches.map((match) => (
              <button
                type="button"
                key={match.id}
                onClick={() => loadAnnotation(match.id)}
                className="workbench-surface-bg rounded-xl border workbench-border p-4 text-left transition hover:border-[#557864]"
              >
                <p className="workbench-foreground font-bold">
                  {match.gene_name || match.normalized_locus}
                </p>
                <p className="workbench-muted mt-1 text-sm">
                  {match.canonical_name} · {match.normalized_locus}
                </p>
                <p className="workbench-muted mt-2 text-xs">
                  {(match.version_count || 0) + 1} saved version
                  {(match.version_count || 0) + 1 === 1 ? "" : "s"}
                </p>
              </button>
            ))}

            {searchedQuery && matches.length === 0 && !isSearching ? (
              <EmptyState query={searchedQuery} />
            ) : null}

            {!searchedQuery ? (
              <p className="workbench-muted rounded-2xl border border-dashed workbench-border p-6 text-sm">
                Search for an annotation to get started.
              </p>
            ) : null}
          </div>
        </section>

        <AnnotationDetail
          annotation={selected}
          profileFields={profileFields}
          versions={versions}
          selectedVersionKey={selectedVersionKey}
          onSelectVersion={setSelectedVersionKey}
          onLoadVersions={loadVersions}
          isLoadingVersions={isLoadingVersions}
        />
      </div>
    </div>
  );
}
