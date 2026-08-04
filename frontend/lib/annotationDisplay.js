export const GENERATED_FIELD_ORDER = [
  ["functional_category", "Functional category"],
  ["function", "Function"],
  ["drug_susc_impact", "Drug susceptibility impact"],
  ["infection_impact", "Infection impact"],
  ["essential_in_vitro", "Essential in vitro"],
  ["essential_in_vivo", "Essential in vivo"],
];

export const FIELD_PROVENANCE_ORTHolog_DERIVED = "ortholog_derived";
export const FIELD_PROVENANCE_TARGET_PLUS_ORTHOLOG = "target_plus_ortholog";

// UI field order is fixed for review readability even though raw JSON preserves
// the full annotation. Helpers expect the backend shape:
// annotation.result.annotation.<generated fields and annotation_metadata>.
const METADATA_FIELDS = [
  ["annotation_notes", "Annotation notes"],
  ["total_papers", "Total papers"],
  ["papers_analyzed", "Papers analyzed"],
  ["sections_analyzed", "Sections analyzed"],
  ["cumulative_relevance", "Cumulative relevance"],
  ["quality_flags", "Quality flags"],
  ["input_tokens", "Input tokens"],
  ["output_tokens", "Output tokens"],
  ["total_tokens", "Total tokens"],
  ["duration", "Duration"],
];

function getAnnotationPayload(annotation) {
  return annotation?.result?.annotation || {};
}

function getMetadata(annotation) {
  return getAnnotationPayload(annotation).annotation_metadata || {};
}

function getLiterature(annotation) {
  return getMetadata(annotation).literature || {};
}

function formatDuration(seconds) {
  if (seconds == null || Number.isNaN(Number(seconds))) {
    return "No supported data";
  }

  const total = Math.max(0, Math.round(Number(seconds)));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remainingSeconds = total % 60;

  if (hours > 0) {
    return `${hours}h ${minutes}m`;
  }
  if (minutes > 0) {
    return `${minutes}m ${remainingSeconds}s`;
  }
  return `${remainingSeconds}s`;
}

export function formatAnnotationValue(value) {
  if (value == null) {
    return "No supported data";
  }
  if (typeof value === "boolean") {
    return value ? "True" : "False";
  }
  if (Array.isArray(value)) {
    if (value.length === 0) {
      return "No supported data";
    }
    return value.map(formatAnnotationValue).join(", ");
  }
  if (typeof value === "object") {
    return JSON.stringify(value, null, 2);
  }

  const text = String(value).trim();
  return text || "No supported data";
}

export function getFieldProvenance(annotation) {
  return getMetadata(annotation).field_provenance || {};
}

export function getOrthologFields(annotation) {
  return getMetadata(annotation).ortholog_fields || {};
}

export function getTargetGoTerms(annotation) {
  const terms = getAnnotationPayload(annotation).go_terms;
  return Array.isArray(terms) ? terms : [];
}

export function getOrthologGoTerms(annotation) {
  const terms = getMetadata(annotation).ortholog_go_terms;
  return Array.isArray(terms) ? terms : [];
}

export function formatGoTermLabel(term) {
  return `${term.id} — ${term.name}`;
}

export function hasOrthologColumn(annotation) {
  // A pass can run (ortholog_pass.ran === true) yet contribute nothing —
  // e.g. the ortholog gene had no papers or no fields to fill. Gate the
  // Ortholog column on actual content, not merely on the pass having run.
  return (
    getOrthologGoTerms(annotation).length > 0 ||
    Object.keys(getOrthologFields(annotation)).length > 0
  );
}

export function formatOrthologSourceLabel(block) {
  if (!block) {
    return "";
  }

  const parts = [];
  if (block.source_gene_id) {
    const name = block.source_gene_name ? ` (${block.source_gene_name})` : "";
    parts.push(`${block.source_gene_id}${name}`);
  } else if (block.source_gene_name) {
    parts.push(String(block.source_gene_name));
  }
  if (block.source_organism) {
    parts.push(String(block.source_organism));
  }
  if (block.identity != null) {
    parts.push(`${Math.round(block.identity * 100)}% identity`);
  }

  return parts.join(" · ");
}

function resolveFieldSpecs(profileFields) {
  if (Array.isArray(profileFields) && profileFields.length > 0) {
    return profileFields
      .filter((field) => field?.key)
      .map((field) => [field.key, field.label || field.key]);
  }
  return GENERATED_FIELD_ORDER;
}

export function getGeneratedFieldRows(annotation, profileFields = null) {
  const payload = getAnnotationPayload(annotation);
  const fieldProvenance = getFieldProvenance(annotation);
  const orthologFields = getOrthologFields(annotation);
  return resolveFieldSpecs(profileFields).map(([key, label]) => {
    const provenance = fieldProvenance[key];
    const orthologEntry = orthologFields[key];
    const orthologDerived =
      provenance === FIELD_PROVENANCE_ORTHolog_DERIVED ||
      provenance === FIELD_PROVENANCE_TARGET_PLUS_ORTHOLOG;
    // When the canonical value already IS the ortholog value, only show the
    // source chip once — avoid repeating the same text under "From ortholog".
    const showOrthologBlock =
      Boolean(orthologEntry) &&
      provenance === FIELD_PROVENANCE_TARGET_PLUS_ORTHOLOG;
    return {
      key,
      label,
      value: formatAnnotationValue(payload[key]),
      orthologDerived,
      orthologOnly: provenance === FIELD_PROVENANCE_ORTHolog_DERIVED,
      orthologBlock: showOrthologBlock
        ? {
            value: formatAnnotationValue(orthologEntry.value),
            sourceLabel: formatOrthologSourceLabel(orthologEntry),
          }
        : orthologEntry && orthologDerived
          ? {
              value: null,
              sourceLabel: formatOrthologSourceLabel(orthologEntry),
            }
          : null,
    };
  });
}

export function getMetadataRows(annotation) {
  const payload = getAnnotationPayload(annotation);
  const metadata = getMetadata(annotation);
  const literature = getLiterature(annotation);
  const llmUsage = metadata.llm_usage || {};
  const values = {
    annotation_notes: payload.annotation_notes,
    total_papers: literature.total_papers_retrieved,
    papers_analyzed: literature.papers_analyzed,
    sections_analyzed: literature.sections_analyzed,
    cumulative_relevance: literature.cumulative_relevance,
    quality_flags: metadata.quality_flags,
    input_tokens: llmUsage.known_input_tokens,
    output_tokens: llmUsage.known_output_tokens,
    total_tokens: llmUsage.known_total_tokens,
    duration: formatDuration(metadata.duration_sec),
  };

  return METADATA_FIELDS.map(([key, label]) => ({
    key,
    label,
    value: formatAnnotationValue(values[key]),
  }));
}

export function getPmcIdsAnalyzed(annotation) {
  const ids = getLiterature(annotation).pmc_ids_analyzed;
  return Array.isArray(ids) ? ids : [];
}
