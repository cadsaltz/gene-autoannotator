"use client";

import { useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";

import { createJob, validateJob } from "../lib/api";
import { buildJobPayload } from "../lib/form";
import { describeSubmitError } from "../lib/queueStatus";

const emptyCustomFields = {
  organism: "",
  strain: "",
  locusRegex: "",
  searchTerms: "",
  targetPatterns: "",
  offTargetPatterns: "",
  excludedSpeciesPatterns: "",
};

export function useJobForm(profiles) {
  const searchParams = useSearchParams();
  const [form, setForm] = useState({
    profile: searchParams.get("profile") || "mtb-h37rv",
    organism: "",
    strain: "",
    locus: searchParams.get("locus") || "",
    name: searchParams.get("name") || "",
    allowOnlineNameLookup: true,
    refreshGeneNameCache: false,
    cacheSuppliedName: false,
    allowOrthologFallback: false,
    orthologProfile: "",
    orthologLocus: "",
    orthologName: "",
    locusRegex: "",
    searchTerms: "",
    targetPatterns: "",
    offTargetPatterns: "",
    excludedSpeciesPatterns: "",
  });

  const selectedProfile = useMemo(
    () => profiles.find((profile) => profile.profile_id === form.profile),
    [profiles, form.profile],
  );
  const isCustomProfile = form.profile === "";

  function updateForm(field, value) {
    setForm((current) => {
      if (field === "profile" && value !== "") {
        return { ...current, ...emptyCustomFields, profile: value };
      }
      return { ...current, [field]: value };
    });
  }

  return { form, updateForm, selectedProfile, isCustomProfile };
}

/** Validates then queues one job; resolves to the confirmation message. */
export async function queueSingleJob(form) {
  const payload = buildJobPayload(form);
  if (!payload.locus && !payload.name) {
    throw new Error("Gene name or locus is required.");
  }
  const validation = await validateJob(payload);
  if (!validation.valid) {
    throw new Error("The target could not be submitted.");
  }
  const created = await createJob(payload);
  const warningText = validation.warnings?.length
    ? ` Warnings: ${validation.warnings.map((warning) => warning.message).join(" ")}`
    : "";
  return `Queued job ${created.job_id}. It will run when earlier jobs finish.${warningText}`;
}

export default function SingleJobForm({
  form,
  updateForm,
  profiles,
  selectedProfile,
  isCustomProfile,
  canSubmit,
  statusMessage,
  setStatusMessage,
  onJobQueued,
  describeError = describeSubmitError,
  showAdvancedTerms = true,
}) {
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();
    setStatusMessage("");
    setIsSubmitting(true);

    try {
      setStatusMessage(await queueSingleJob(form));
      await onJobQueued();
    } catch (error) {
      setStatusMessage(describeError(error));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <form className="mt-6 grid gap-4" onSubmit={handleSubmit}>
      <label className="grid gap-2 text-sm font-medium">
        Profile
        <select
          value={form.profile}
          onChange={(event) => updateForm("profile", event.target.value)}
          className="workbench-input"
        >
          <option value="">Custom organism/strain</option>
          {profiles.map((profile) => (
            <option key={profile.profile_id} value={profile.profile_id}>
              {profile.canonical_name}
            </option>
          ))}
        </select>
      </label>

      {!isCustomProfile && selectedProfile ? (
        <div className="workbench-muted-bg workbench-muted rounded-xl border workbench-border p-4 text-sm">
          Expected locus format:{" "}
          <code className="rounded bg-[#eee6d9] px-1 py-0.5">
            {selectedProfile.locus_regex}
          </code>
        </div>
      ) : null}

      {isCustomProfile ? (
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="grid gap-2 text-sm font-medium">
            Organism
            <input
              value={form.organism}
              onChange={(event) => updateForm("organism", event.target.value)}
              className="workbench-input"
              placeholder="Trypanosoma cruzi"
            />
          </label>
          <label className="grid gap-2 text-sm font-medium">
            Strain
            <input
              value={form.strain}
              onChange={(event) => updateForm("strain", event.target.value)}
              className="workbench-input"
              placeholder="CL Brener"
            />
          </label>
        </div>
      ) : null}

      <label className="grid gap-2 text-sm font-medium">
        Locus (optional if gene name is supplied)
        <input
          value={form.locus}
          onChange={(event) => updateForm("locus", event.target.value)}
          className="workbench-input"
          placeholder="Rv0001 or TcCLB.503799.4"
        />
      </label>

      <label className="grid gap-2 text-sm font-medium">
        Gene name (optional if locus is supplied)
        <input
          value={form.name}
          onChange={(event) => updateForm("name", event.target.value)}
          className="workbench-input"
          placeholder="dnaA"
        />
      </label>

      <div className="workbench-muted-bg grid gap-3 rounded-xl border workbench-border p-4 text-sm">
        <label className="flex items-center gap-3">
          <input
            type="checkbox"
            checked={form.allowOnlineNameLookup}
            onChange={(event) => updateForm("allowOnlineNameLookup", event.target.checked)}
          />
          Allow online gene-name lookup
        </label>
        <label className="flex items-center gap-3">
          <input
            type="checkbox"
            checked={form.refreshGeneNameCache}
            onChange={(event) => updateForm("refreshGeneNameCache", event.target.checked)}
          />
          Refresh gene-name cache
        </label>
        <label className="flex items-center gap-3">
          <input
            type="checkbox"
            checked={form.cacheSuppliedName}
            onChange={(event) => updateForm("cacheSuppliedName", event.target.checked)}
          />
          Cache supplied gene name
        </label>
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
            Leave the ortholog fields blank for automatic ortholog lookup across
            all profiled organisms. Choose a profile without a locus to restrict
            automatic search to that organism. Supply a locus to pin a specific
            ortholog gene.
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
          <label className="grid gap-2 font-medium">
            Ortholog locus
            <input
              value={form.orthologLocus}
              onChange={(event) => updateForm("orthologLocus", event.target.value)}
              className="workbench-input"
              placeholder="Leave blank to search within the selected profile"
            />
          </label>
          <label className="grid gap-2 font-medium">
            Ortholog gene name (optional)
            <input
              value={form.orthologName}
              onChange={(event) => updateForm("orthologName", event.target.value)}
              className="workbench-input"
              placeholder="octT"
            />
          </label>
        </div>
      ) : null}

      {isCustomProfile && showAdvancedTerms ? (
        <details className="workbench-muted-bg rounded-xl border workbench-border p-4 text-sm">
          <summary className="cursor-pointer font-bold">Advanced custom organism terms</summary>
          <div className="mt-4 grid gap-4">
            <label className="grid gap-2">
              Locus regex
              <input
                value={form.locusRegex}
                onChange={(event) => updateForm("locusRegex", event.target.value)}
                className="workbench-input"
                placeholder="^CUS_\\d+$"
              />
            </label>
            <label className="grid gap-2">
              Search terms, one per line
              <textarea
                value={form.searchTerms}
                onChange={(event) => updateForm("searchTerms", event.target.value)}
                className="workbench-input min-h-24"
              />
            </label>
            <label className="grid gap-2">
              Target organism patterns, one per line
              <textarea
                value={form.targetPatterns}
                onChange={(event) => updateForm("targetPatterns", event.target.value)}
                className="workbench-input min-h-24"
              />
            </label>
            <label className="grid gap-2">
              Off-target patterns, one per line
              <textarea
                value={form.offTargetPatterns}
                onChange={(event) => updateForm("offTargetPatterns", event.target.value)}
                className="workbench-input min-h-24"
              />
            </label>
            <label className="grid gap-2">
              Excluded species patterns, one per line
              <textarea
                value={form.excludedSpeciesPatterns}
                onChange={(event) => updateForm("excludedSpeciesPatterns", event.target.value)}
                className="workbench-input min-h-24"
              />
            </label>
          </div>
        </details>
      ) : null}

      {statusMessage ? (
        <p className="workbench-amber-bg rounded-xl border workbench-border p-4 text-sm text-[#5f4b2e]">
          {statusMessage}
        </p>
      ) : null}

      <button
        type="submit"
        disabled={!canSubmit || isSubmitting}
        suppressHydrationWarning
        className="workbench-button workbench-button-primary min-h-11 px-5 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {isSubmitting ? "Submitting..." : "Queue annotation job"}
      </button>
    </form>
  );
}
