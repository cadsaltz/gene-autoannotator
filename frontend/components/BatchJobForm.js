"use client";

import { useState } from "react";

import { createBatch, validateBatch } from "../lib/api";
import {
  buildBatchPayload,
  parseGeneFileName,
  parseGeneListText,
  readGeneFile,
} from "../lib/form";

const GENE_LIST_PLACEHOLDER =
  "One gene per line — locus (e.g. Rv0001) or gene name (e.g. dnaA). Commas and tabs also work.";

function statusBadgeClass(status) {
  if (status === "ready") return "bg-[#dbe8df] text-[#2d4a38]";
  if (status === "ambiguous") return "bg-[#f5e8c8] text-[#5f4b2e]";
  if (status === "duplicate_skipped") return "bg-[#e8e3db] text-[#5a5248]";
  return "bg-[#f3d9dc] text-[#7a3a41]";
}

function statusLabel(status) {
  if (status === "duplicate_skipped") return "duplicate";
  return status;
}

function applySelectedLoci(entries, selectedLoci) {
  return entries.map((entry, index) => {
    const selected = selectedLoci[index + 1];
    if (selected) {
      return { ...entry, selected_locus: selected };
    }
    return entry;
  });
}

function formatSummary(summary) {
  if (!summary) {
    return null;
  }
  return `${summary.ready} ready · ${summary.invalid} invalid · ${summary.duplicate_skipped} duplicate · ${summary.ambiguous} ambiguous`;
}

function PreviewStatusBadge({ status }) {
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-xs font-bold uppercase tracking-wide ${statusBadgeClass(status)}`}
    >
      {statusLabel(status)}
    </span>
  );
}

export default function BatchJobForm({
  form,
  updateForm,
  profiles,
  selectedProfile,
  isCustomProfile: _isCustomProfile,
  canSubmit,
  onBatchSubmitted,
  setStatusMessage,
}) {
  const [geneListText, setGeneListText] = useState("");
  const [preview, setPreview] = useState(null);
  const [selectedLoci, setSelectedLoci] = useState({});
  const [isValidating, setIsValidating] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const readyCount = preview?.summary?.ready ?? 0;
  const ambiguousCount = preview?.summary?.ambiguous ?? 0;
  const canQueue = canSubmit && !isValidating && !isSubmitting && readyCount >= 1 && ambiguousCount === 0;

  async function runValidation(nextSelectedLoci = selectedLoci) {
    setIsValidating(true);
    setStatusMessage("");

    try {
      const parsed = parseGeneListText(geneListText);
      const entries = applySelectedLoci(parsed, nextSelectedLoci);
      const payload = buildBatchPayload(form, entries);
      const result = await validateBatch(payload);
      setPreview(result);
    } catch (error) {
      setPreview(null);
      setStatusMessage(error.message);
    } finally {
      setIsValidating(false);
    }
  }

  async function handleValidate(event) {
    event.preventDefault();
    await runValidation();
  }

  async function handleCandidateChange(line, selectedLocus) {
    const nextSelectedLoci = { ...selectedLoci, [line]: selectedLocus };
    setSelectedLoci(nextSelectedLoci);
    await runValidation(nextSelectedLoci);
  }

  async function handleFileChange(event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) {
      return;
    }

    const lowerName = file.name.toLowerCase();
    if (lowerName.endsWith(".xlsx") || lowerName.endsWith(".xls")) {
      setStatusMessage("Use .txt, .csv, or .tsv — or paste from Excel");
      return;
    }

    try {
      parseGeneFileName(file.name);
      await readGeneFile(file);
      const text = await file.text();
      setGeneListText(text);
      setPreview(null);
      setSelectedLoci({});
      setStatusMessage("");
    } catch (error) {
      setStatusMessage(error.message);
    }
  }

  async function handleSubmit(event) {
    event.preventDefault();
    if (!canQueue) {
      return;
    }

    setIsSubmitting(true);
    setStatusMessage("");

    try {
      const parsed = parseGeneListText(geneListText);
      const entries = applySelectedLoci(parsed, selectedLoci);
      const payload = buildBatchPayload(form, entries);
      const result = await createBatch(payload);
      onBatchSubmitted(result.batch_id, result);
      const jobCount = result.job_ids?.length ?? readyCount;
      setStatusMessage(
        `Queued batch ${result.batch_id} with ${jobCount} annotation${jobCount === 1 ? "" : "s"}.`,
      );
      setPreview(null);
      setSelectedLoci({});
    } catch (error) {
      setStatusMessage(error.message);
    } finally {
      setIsSubmitting(false);
    }
  }

  function handleGeneListChange(event) {
    setGeneListText(event.target.value);
    setPreview(null);
    setSelectedLoci({});
  }

  return (
    <form className="grid gap-4" onSubmit={handleSubmit}>
      {!_isCustomProfile && selectedProfile ? (
        <div className="workbench-muted-bg workbench-muted rounded-xl border workbench-border p-4 text-sm">
          Expected locus format:{" "}
          <code className="rounded bg-[#eee6d9] px-1 py-0.5">{selectedProfile.locus_regex}</code>
        </div>
      ) : null}

      <div className="workbench-muted-bg grid gap-3 rounded-xl border workbench-border p-4 text-sm">
        <label className="flex items-center gap-3">
          <input
            type="checkbox"
            checked={form.allowOrthologFallback}
            onChange={(event) => updateForm("allowOrthologFallback", event.target.checked)}
          />
          Allow ortholog fallback
        </label>
      </div>

      {form.allowOrthologFallback ? (
        <div className="workbench-muted-bg grid gap-4 rounded-xl border workbench-border p-4 text-sm">
          <p className="workbench-muted">
            Optionally constrain automatic ortholog search to one organism profile.
            Each gene in the batch finds its own best sequence match within that
            profile. A single ortholog gene cannot be reused across the batch.
          </p>
          <label className="grid gap-2 font-medium">
            Ortholog organism/profile
            <select
              value={form.orthologProfile}
              onChange={(event) => updateForm("orthologProfile", event.target.value)}
              className="workbench-input"
            >
              <option value="">Automatic (any profiled organism)</option>
              {profiles.map((profile) => (
                <option key={profile.profile_id} value={profile.profile_id}>
                  {profile.canonical_name}
                </option>
              ))}
            </select>
          </label>
        </div>
      ) : null}

      <label className="grid gap-2 text-sm font-medium">
        Gene list
        <textarea
          value={geneListText}
          onChange={handleGeneListChange}
          className="workbench-input min-h-40 font-mono text-sm"
          placeholder={GENE_LIST_PLACEHOLDER}
        />
      </label>

      <div className="grid gap-2">
        <label className="grid gap-2 text-sm font-medium">
          Upload plain-text list
          <input
            type="file"
            accept=".txt,.csv,.tsv"
            onChange={handleFileChange}
            className="workbench-input py-2"
          />
        </label>
        <p className="workbench-muted text-xs leading-5">
          Upload a list: one identifier per line, or two columns locus,name. For Excel, copy a
          column here or Save As CSV.
        </p>
      </div>

      <button
        type="button"
        onClick={handleValidate}
        disabled={!canSubmit || isValidating || isSubmitting || !geneListText.trim()}
        className="workbench-button workbench-button-secondary min-h-11 px-5 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {isValidating ? "Validating..." : "Validate batch"}
      </button>

      {preview ? (
        <div className="grid gap-4">
          <p className="workbench-foreground text-sm font-semibold">{formatSummary(preview.summary)}</p>

          <div className="overflow-x-auto rounded-xl border workbench-border">
            <table className="min-w-full text-left text-sm">
              <thead className="workbench-muted-bg workbench-muted text-xs font-bold uppercase tracking-[0.08em]">
                <tr>
                  <th className="px-3 py-2">Line</th>
                  <th className="px-3 py-2">Input</th>
                  <th className="px-3 py-2">Resolved locus</th>
                  <th className="px-3 py-2">Resolved name</th>
                  <th className="px-3 py-2">Status</th>
                  <th className="px-3 py-2">Warnings</th>
                </tr>
              </thead>
              <tbody>
                {preview.entries.map((entry) => (
                  <tr key={entry.line} className="border-t workbench-border">
                    <td className="px-3 py-2 align-top">{entry.line}</td>
                    <td className="px-3 py-2 align-top font-mono text-xs">{entry.input}</td>
                    <td className="px-3 py-2 align-top font-mono text-xs">
                      {entry.status === "ambiguous" ? (
                        <select
                          value={selectedLoci[entry.line] || ""}
                          onChange={(event) => handleCandidateChange(entry.line, event.target.value)}
                          className="workbench-input text-xs"
                        >
                          <option value="">Choose locus…</option>
                          {entry.candidates.map((candidate) => (
                            <option key={candidate} value={candidate}>
                              {candidate}
                            </option>
                          ))}
                        </select>
                      ) : (
                        entry.resolved_locus || "—"
                      )}
                    </td>
                    <td className="px-3 py-2 align-top">{entry.resolved_name || "—"}</td>
                    <td className="px-3 py-2 align-top">
                      <PreviewStatusBadge status={entry.status} />
                    </td>
                    <td className="px-3 py-2 align-top text-xs text-[#5f4b2e]">
                      {entry.warnings?.length
                        ? entry.warnings.map((warning) => warning.message).join(" ")
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <button
            type="submit"
            disabled={!canQueue}
            suppressHydrationWarning
            className="workbench-button workbench-button-primary min-h-11 px-5 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isSubmitting
              ? "Queueing..."
              : `Queue ${readyCount} annotation${readyCount === 1 ? "" : "s"}`}
          </button>
        </div>
      ) : null}
    </form>
  );
}
