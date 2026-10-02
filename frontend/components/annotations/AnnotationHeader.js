"use client";

import Link from "next/link";
import { useState } from "react";

import { getFieldCoverage, getNameSource } from "../../lib/annotationSummary";
import { buildVersionOptions, CURRENT_VERSION_KEY, getTotalVersionCount } from "../../lib/annotationVersions";
import { buildJobPrefillHref } from "../../lib/form";
import { RESEARCH_DISCLAIMER } from "../../lib/legal";
import { AlertIcon, ChevronDownIcon, CloseIcon, RefreshIcon } from "../icons";
import { Badge } from "./ui";

const DISCLAIMER_HIDDEN_KEY = "ga-disclaimer-hidden";

function readDisclaimerHidden() {
  try {
    return window.sessionStorage.getItem(DISCLAIMER_HIDDEN_KEY) === "1";
  } catch {
    return false;
  }
}

export default function AnnotationHeader({ annotation, view, versions, selectedVersionKey, onSelectVersion }) {
  const [disclaimerHidden, setDisclaimerHidden] = useState(readDisclaimerHidden);
  const options = buildVersionOptions(annotation, versions);
  const total = getTotalVersionCount(annotation, versions);
  const selected = options.find((option) => option.key === selectedVersionKey) || options[0];
  const viewingHistorical = selectedVersionKey !== CURRENT_VERSION_KEY;
  const coverage = getFieldCoverage(view);
  const nameSource = getNameSource(view);
  const geneName = view.gene_name || annotation.normalized_locus;

  function hideDisclaimer() {
    try {
      window.sessionStorage.setItem(DISCLAIMER_HIDDEN_KEY, "1");
    } catch {
      // Storage can be unavailable (private mode, quota); still hide for this render.
    }
    setDisclaimerHidden(true);
  }

  return (
    <header>
      <nav aria-label="Breadcrumb" className="flex flex-wrap items-center gap-2 text-sm font-medium text-fg-muted">
        <span>Annotations</span>
        <span aria-hidden="true">/</span>
        <span>{annotation.canonical_name}</span>
        <span aria-hidden="true">/</span>
        <span aria-current="page" className="font-semibold text-brand-fg">
          {geneName}
        </span>
      </nav>

      <div className="mt-4 flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div className="min-w-0">
          <h1 className="flex flex-wrap items-baseline gap-x-3 text-3xl font-semibold tracking-tight text-fg">
            {geneName}
            <span className="font-mono text-base font-normal tracking-normal text-fg-muted">
              {annotation.normalized_locus}
            </span>
          </h1>
          <div className="mt-2 flex flex-wrap gap-2">
            {annotation.canonical_name ? <Badge tone="brand">{annotation.canonical_name}</Badge> : null}
            {viewingHistorical ? (
              <Badge tone="warning" dot>
                Older version {selected.versionNumber} of {total}
              </Badge>
            ) : (
              <Badge dot>
                Latest · version {total} of {total}
              </Badge>
            )}
            {coverage ? (
              <Badge tone={coverage.supported === coverage.total ? "success" : "warning"} dot>
                {coverage.supported === coverage.total
                  ? `All ${coverage.total} fields supported`
                  : `${coverage.supported} of ${coverage.total} fields supported`}
              </Badge>
            ) : null}
            {nameSource ? <Badge>Name: {nameSource}</Badge> : null}
          </div>
        </div>

        <div className="flex shrink-0 flex-wrap gap-3">
          {options.length > 1 ? (
            <label className="relative">
              <span className="sr-only">Version</span>
              <select
                value={selectedVersionKey}
                onChange={(event) => onSelectVersion(event.target.value)}
                className="workbench-button workbench-button-secondary cursor-pointer appearance-none pr-9"
              >
                {options.map((option) => (
                  <option key={option.key} value={option.key}>
                    Version {option.versionNumber}
                    {option.isCurrent ? " (latest)" : ""}
                  </option>
                ))}
              </select>
              <ChevronDownIcon className="pointer-events-none absolute top-1/2 right-3 -translate-y-1/2 text-fg-muted" />
            </label>
          ) : null}
          {!viewingHistorical ? (
            <Link
              href={buildJobPrefillHref(annotation)}
              className="workbench-button workbench-button-primary"
            >
              <RefreshIcon />
              Re-run annotation
            </Link>
          ) : null}
        </div>
      </div>

      {!disclaimerHidden ? (
        <div
          role="note"
          className="mt-5 flex items-start gap-3 rounded-lg border border-warning-line bg-warning-tint px-3.5 py-2.5 text-sm text-warning-fg"
        >
          <AlertIcon size={18} className="mt-px" />
          <p className="flex-1">
            {RESEARCH_DISCLAIMER}{" "}
            <Link href="/legal/disclaimer" className="font-semibold underline underline-offset-2">
              Read the disclaimer
            </Link>
          </p>
          <button
            type="button"
            onClick={hideDisclaimer}
            aria-label="Hide the disclaimer for this session"
            className="rounded p-0.5 transition hover:bg-warning-line"
          >
            <CloseIcon />
          </button>
        </div>
      ) : null}

      {viewingHistorical ? (
        <div
          role="status"
          className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line bg-surface-muted px-3.5 py-2.5 text-sm text-fg-secondary"
        >
          <span>You are viewing an older saved version.</span>
          <button
            type="button"
            onClick={() => onSelectVersion(CURRENT_VERSION_KEY)}
            className="font-semibold text-brand-fg hover:underline"
          >
            Back to latest
          </button>
        </div>
      ) : null}
    </header>
  );
}
