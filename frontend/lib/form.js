import { splitLines } from "./profileStore.js";

const HEADER_TOKENS = new Set(["locus", "gene", "name", "id"]);
const ALLOWED_GENE_FILE_EXTENSIONS = [".txt", ".csv", ".tsv"];
const TWO_COLUMN_ERROR = "Only one column or two columns (locus, name) are supported.";

export class BatchParseError extends Error {
  constructor(message) {
    super(message);
    this.name = "BatchParseError";
  }
}

function cleanToken(value) {
  let token = String(value).trim();
  if (token.length >= 2 && token[0] === '"' && token[token.length - 1] === '"') {
    token = token.slice(1, -1).trim();
  }
  return token || null;
}

function detectFormat(lines, { delimiter } = {}) {
  if (delimiter === "tab") {
    const fieldCounts = lines.map((line) => line.split("\t").length);
    if (fieldCounts.some((count) => count >= 3)) {
      throw new BatchParseError(TWO_COLUMN_ERROR);
    }
    if (fieldCounts.some((count) => count === 2)) {
      return ["two_column", "\t"];
    }
  }

  const fieldCounts = lines.map((line) => line.split(/[,\t]/).length);
  if (lines.length === 1 && fieldCounts[0] >= 3) {
    const tokens = lines[0].split(/[,\t]/).map(cleanToken);
    if (tokens.length > 0 && tokens.every((token) => token && token.length === 1)) {
      throw new BatchParseError(TWO_COLUMN_ERROR);
    }
  }
  if (fieldCounts.some((count) => count >= 3)) {
    throw new BatchParseError(TWO_COLUMN_ERROR);
  }
  if (fieldCounts.some((count) => count === 2)) {
    const splitDelim = lines.every((line) => line.includes("\t") && !line.includes(","))
      ? "\t"
      : ",";
    return ["two_column", splitDelim];
  }
  return ["single_column", null];
}

function parseSingleColumn(lines) {
  const entries = [];
  for (const line of lines) {
    for (const token of line.split(/[\n,;\t]+/)) {
      const cleaned = cleanToken(token);
      if (cleaned) {
        entries.push({ input: cleaned });
      }
    }
  }
  if (entries.length === 0) {
    throw new BatchParseError("No genes found.");
  }
  return entries;
}

function parseTwoColumn(lines, splitDelim) {
  let dataLines = [...lines];
  const firstFields = dataLines[0].split(splitDelim).map((field) => field.trim());
  if (
    firstFields.length === 2
    && firstFields.every((field) => !field || HEADER_TOKENS.has(field.toLowerCase()))
  ) {
    dataLines = dataLines.slice(1);
  }

  const entries = [];
  for (const line of dataLines) {
    const fields = line.split(splitDelim);
    if (fields.length !== 2) {
      throw new BatchParseError(TWO_COLUMN_ERROR);
    }
    const locus = cleanToken(fields[0]) || null;
    const name = cleanToken(fields[1]) || null;
    if (!locus && !name) {
      continue;
    }
    entries.push({ locus, name });
  }
  if (entries.length === 0) {
    throw new BatchParseError("No genes found.");
  }
  return entries;
}

export function parseGeneListText(text, options = {}) {
  const normalized = String(text ?? "").replace(/^\ufeff/, "");
  const lines = normalized.split(/\r?\n/);
  const nonCommentLines = lines.filter(
    (line) => line.trim() && !line.trim().startsWith("#"),
  );
  if (nonCommentLines.length === 0) {
    throw new BatchParseError("No genes found.");
  }

  const [mode, splitDelim] = detectFormat(nonCommentLines, options);
  if (mode === "two_column") {
    return parseTwoColumn(nonCommentLines, splitDelim);
  }
  return parseSingleColumn(nonCommentLines);
}

export function parseGeneFileName(filename) {
  const lower = String(filename ?? "").toLowerCase();
  const allowed = ALLOWED_GENE_FILE_EXTENSIONS.some((extension) => lower.endsWith(extension));
  if (!allowed) {
    throw new Error("Use .txt, .csv, or .tsv — or paste from Excel");
  }
  return lower.slice(lower.lastIndexOf("."));
}

export async function readGeneFile(file) {
  parseGeneFileName(file?.name ?? "");
  const text = await file.text();
  return parseGeneListText(text);
}

function buildBatchOptionsPayload(values) {
  const profile = values.profile?.trim();
  const payload = {
    allow_online_name_lookup: Boolean(values.allowOnlineNameLookup),
    refresh_gene_name_cache: Boolean(values.refreshGeneNameCache),
    cache_supplied_name: Boolean(values.cacheSuppliedName),
    allow_ortholog_fallback: Boolean(values.allowOrthologFallback),
  };

  // Batch ortholog overrides are profile-only: each gene finds its own best
  // match within the chosen organism. Locus/name from the shared form are ignored.
  if (values.allowOrthologFallback) {
    const orthologProfile = values.orthologProfile?.trim();
    if (orthologProfile) {
      payload.ortholog_override = {
        profile_id: orthologProfile,
        locus: null,
        name: null,
      };
    }
  }

  if (profile) {
    payload.profile = profile;
    return payload;
  }

  for (const [source, target] of [
    ["organism", "organism"],
    ["strain", "strain"],
  ]) {
    const value = values[source]?.trim();
    if (value) {
      payload[target] = value;
    }
  }

  const locusRegex = values.locusRegex?.trim();
  if (locusRegex) {
    payload.locus_regex = locusRegex;
  }

  for (const [source, target] of [
    ["searchTerms", "search_terms"],
    ["targetPatterns", "target_patterns"],
    ["offTargetPatterns", "off_target_patterns"],
    ["excludedSpeciesPatterns", "excluded_species_patterns"],
  ]) {
    const optionEntries = splitLines(values[source]);
    if (optionEntries.length > 0) {
      payload[target] = optionEntries;
    }
  }

  return payload;
}

export function buildBatchPayload(values, entries) {
  return {
    ...buildBatchOptionsPayload(values),
    entries,
  };
}

export function buildJobPayload(values) {
  // Convert React form naming to the snake_case FastAPI/Pydantic contract while
  // omitting empty optional fields so backend defaults remain authoritative.
  const profile = values.profile?.trim();
  const payload = {
    allow_online_name_lookup: Boolean(values.allowOnlineNameLookup),
    refresh_gene_name_cache: Boolean(values.refreshGeneNameCache),
    cache_supplied_name: Boolean(values.cacheSuppliedName),
    allow_ortholog_fallback: Boolean(values.allowOrthologFallback),
  };

  // Attach the ortholog override when fallback is enabled. Profile + locus pins
  // a manual ortholog; profile alone constrains automatic SSDB search.
  if (values.allowOrthologFallback) {
    const orthologProfile = values.orthologProfile?.trim();
    const orthologLocus = values.orthologLocus?.trim();
    if (orthologProfile) {
      payload.ortholog_override = {
        profile_id: orthologProfile,
        locus: orthologLocus || null,
        name: orthologLocus ? values.orthologName?.trim() || null : null,
      };
    }
  }

  for (const [source, target] of [
    ["profile", "profile"],
    ["locus", "locus"],
    ["name", "name"],
  ]) {
    const value = values[source]?.trim();
    if (value) {
      payload[target] = value;
    }
  }

  if (profile) {
    return payload;
  }

  for (const [source, target] of [
    ["organism", "organism"],
    ["strain", "strain"],
  ]) {
    const value = values[source]?.trim();
    if (value) {
      payload[target] = value;
    }
  }

  const locusRegex = values.locusRegex?.trim();
  if (locusRegex) {
    payload.locus_regex = locusRegex;
  }

  for (const [source, target] of [
    ["searchTerms", "search_terms"],
    ["targetPatterns", "target_patterns"],
    ["offTargetPatterns", "off_target_patterns"],
    ["excludedSpeciesPatterns", "excluded_species_patterns"],
  ]) {
    const entries = splitLines(values[source]);
    if (entries.length > 0) {
      payload[target] = entries;
    }
  }

  return payload;
}

export function buildJobPrefillHref(annotation) {
  const params = new URLSearchParams();
  if (annotation.profile_id) {
    params.set("profile", annotation.profile_id);
  }
  if (annotation.normalized_locus) {
    params.set("locus", annotation.normalized_locus);
  }
  if (annotation.gene_name) {
    params.set("name", annotation.gene_name);
  }
  return `/jobs?${params.toString()}`;
}

export function formatElapsedSeconds(seconds) {
  if (seconds == null || Number.isNaN(Number(seconds))) {
    return "Not started";
  }

  const total = Math.max(0, Math.floor(Number(seconds)));
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

export function secondsSince(isoTimestamp) {
  if (!isoTimestamp) {
    return null;
  }
  return Math.max(0, Math.floor((Date.now() - Date.parse(isoTimestamp)) / 1000));
}

export function formatJobElapsed(job, nowMs = Date.now()) {
  if (!job?.started_at) {
    return "--";
  }

  const startedMs = Date.parse(job.started_at);
  if (Number.isNaN(startedMs)) {
    return "--";
  }

  const finishedMs = job.finished_at ? Date.parse(job.finished_at) : null;
  const endMs = finishedMs != null && !Number.isNaN(finishedMs) ? finishedMs : nowMs;
  return formatElapsedSeconds((endMs - startedMs) / 1000);
}
