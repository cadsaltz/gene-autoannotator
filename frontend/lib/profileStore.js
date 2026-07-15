export function splitLines(value) {
  return String(value || "")
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export const REQUIRED_DEFAULT_FIELDS = [
  {
    key: "function",
    label: "Function",
    description:
      "What the gene product does for the cell (one or two concise sentences). Use null if the excerpt does not support this.",
    type: "string",
    required: true,
    inference_strategy: "paper_llm",
    ortholog_allowed: true,
  },
  {
    key: "functional_category",
    label: "Functional category",
    description:
      "One or more general cellular functions (e.g., cell wall, respiration, virulence, DNA replication/repair). Use null if not supported.",
    type: "array:string",
    required: true,
    inference_strategy: "go_terms",
    ortholog_allowed: false,
  },
];

export const BUILTIN_OPTIONAL_FIELD_TEMPLATES = [
  {
    key: "drug_susc_impact",
    label: "Drug susceptibility impact",
    description:
      "Impact on {species_name} drug susceptibility (one or two concise sentences). Only state effects explicitly reported in the excerpt. Use null otherwise.",
    type: "string",
    required: false,
    inference_strategy: "paper_llm",
    ortholog_allowed: false,
  },
  {
    key: "infection_impact",
    label: "Infection impact",
    description:
      "Impact on {species_name} infection (one or two concise sentences). Only state effects explicitly reported in the excerpt. Use null otherwise.",
    type: "string",
    required: false,
    inference_strategy: "paper_llm",
    ortholog_allowed: false,
  },
  {
    key: "essential_in_vitro",
    label: "Essential in vitro",
    description:
      "Whether the gene is essential for {species_name} survival in vitro. Use true or false only when the excerpt reports direct experimental evidence. Otherwise use null.",
    type: "boolean",
    required: false,
    inference_strategy: "paper_llm",
    ortholog_allowed: false,
  },
  {
    key: "essential_in_vivo",
    label: "Essential in vivo",
    description:
      "Whether the gene is essential for {species_name} survival in vivo. Use true or false only when the excerpt reports direct experimental evidence. Otherwise use null.",
    type: "boolean",
    required: false,
    inference_strategy: "paper_llm",
    ortholog_allowed: false,
  },
];

export function canEnableOrthologAllowed(keggOrganismCode) {
  return Boolean(String(keggOrganismCode || "").trim());
}

export function createEmptyCustomField() {
  return {
    key: "",
    label: "",
    description: "",
    type: "string",
    required: false,
    inference_strategy: "paper_llm",
    ortholog_allowed: false,
  };
}

export function customFieldFromTemplate(template) {
  return { ...template };
}

export function sanitizeCustomFieldsForPayload(customFields, keggOrganismCode) {
  const keggEnabled = canEnableOrthologAllowed(keggOrganismCode);
  return (customFields || []).map((field) => ({
    ...field,
    ortholog_allowed: keggEnabled ? Boolean(field.ortholog_allowed) : false,
  }));
}

export function defaultFieldOrthologFromApi(profile) {
  const base = Object.fromEntries(
    REQUIRED_DEFAULT_FIELDS.map((field) => [field.key, field.ortholog_allowed]),
  );
  return { ...base, ...(profile?.default_field_ortholog || {}) };
}

export function sanitizeDefaultFieldOrthologForPayload(
  defaultFieldOrtholog,
  keggOrganismCode,
) {
  const keggEnabled = canEnableOrthologAllowed(keggOrganismCode);
  return Object.fromEntries(
    REQUIRED_DEFAULT_FIELDS.map((field) => [
      field.key,
      keggEnabled ? Boolean(defaultFieldOrtholog?.[field.key]) : false,
    ]),
  );
}

export function resolveProfileFieldsForDisplay(profile) {
  const defaultOrtholog = defaultFieldOrthologFromApi(profile);
  const keggEnabled = canEnableOrthologAllowed(profile?.kegg_organism_code);
  const defaults = REQUIRED_DEFAULT_FIELDS.map((field) => ({
    ...field,
    ortholog_allowed: keggEnabled ? Boolean(defaultOrtholog[field.key]) : false,
    isDefault: true,
  }));
  const custom = profileCustomFieldsFromApi(profile).map((field) => ({
    ...field,
    ortholog_allowed: keggEnabled ? Boolean(field.ortholog_allowed) : false,
    isDefault: false,
  }));
  return [...defaults, ...custom];
}

export function profileCustomFieldsFromApi(profile) {
  const raw = profile?.custom_fields?.length
    ? profile.custom_fields
    : profile?.annotation_fields || [];
  return raw.map((field) => ({ ...field }));
}

export function buildProfilePayload(values) {
  const keggOrganismCode = values.keggOrganismCode?.trim() || null;
  const payload = {
    profile_id: values.profileId?.trim(),
    canonical_name: values.canonicalName?.trim(),
    species_name: values.speciesName?.trim(),
    strain: values.strain?.trim() || null,
    synonyms: splitLines(values.synonyms),
    species_synonyms: splitLines(values.speciesSynonyms),
    strain_synonyms: splitLines(values.strainSynonyms),
    locus_regex: values.locusRegex?.trim() || null,
    search_terms: splitLines(values.searchTerms),
    target_patterns: splitLines(values.targetPatterns),
    off_target_patterns: splitLines(values.offTargetPatterns),
    excluded_species_patterns: splitLines(values.excludedSpeciesPatterns),
    kegg_organism_code: keggOrganismCode,
    kegg_locus_regex: values.keggLocusRegex?.trim() || null,
    custom_fields: sanitizeCustomFieldsForPayload(values.customFields, keggOrganismCode),
    default_field_ortholog: sanitizeDefaultFieldOrthologForPayload(
      values.defaultFieldOrtholog,
      keggOrganismCode,
    ),
  };
  return payload;
}

export function profileToForm(profile) {
  return {
    profileId: profile.profile_id || "",
    canonicalName: profile.canonical_name || "",
    speciesName: profile.species_name || "",
    strain: profile.strain || "",
    synonyms: (profile.synonyms || []).join("\n"),
    speciesSynonyms: (profile.species_synonyms || []).join("\n"),
    strainSynonyms: (profile.strain_synonyms || []).join("\n"),
    locusRegex: profile.locus_regex || "",
    searchTerms: (profile.search_terms || []).join("\n"),
    targetPatterns: (profile.target_patterns || []).join("\n"),
    offTargetPatterns: (profile.off_target_patterns || []).join("\n"),
    excludedSpeciesPatterns: (profile.excluded_species_patterns || []).join("\n"),
    keggOrganismCode: profile.kegg_organism_code || "",
    keggLocusRegex: profile.kegg_locus_regex || "",
    customFields: profileCustomFieldsFromApi(profile),
    defaultFieldOrtholog: defaultFieldOrthologFromApi(profile),
  };
}
