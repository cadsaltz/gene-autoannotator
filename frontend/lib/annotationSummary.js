import { formatDuration, getAnnotationPayload, getLiterature, getMetadata } from "./annotationDisplay.js";

const MISSING = "—";

function isNumber(value) {
  return typeof value === "number" && Number.isFinite(value);
}

export function getStatCells(annotation, { locale, timeZone } = {}) {
  const metadata = getMetadata(annotation);
  const literature = getLiterature(annotation);
  const generatedRaw = annotation?.generated_at || metadata.generated_at;
  const generated = generatedRaw ? new Date(generatedRaw) : null;
  const hasDate = Boolean(generated) && !Number.isNaN(generated.getTime());
  const cumulative = literature.cumulative_relevance;
  const target = literature.target_relevance;
  const flags = metadata.quality_flags;

  return [
    {
      key: "generated",
      label: "Generated",
      value: hasDate
        ? generated.toLocaleDateString(locale, { year: "numeric", month: "short", day: "numeric", timeZone })
        : MISSING,
      title: hasDate ? generated.toLocaleString(locale, { timeZone }) : undefined,
    },
    {
      key: "papers",
      label: "Papers analyzed",
      value: isNumber(literature.papers_analyzed) ? String(literature.papers_analyzed) : MISSING,
      detail: isNumber(literature.total_papers_retrieved)
        ? `of ${literature.total_papers_retrieved} retrieved`
        : undefined,
    },
    {
      key: "sections",
      label: "Sections",
      value: isNumber(literature.sections_analyzed) ? String(literature.sections_analyzed) : MISSING,
    },
    {
      key: "relevance",
      label: "Relevance",
      value: isNumber(cumulative) ? cumulative.toFixed(2) : MISSING,
      detail: isNumber(target) ? `/ ${target.toFixed(1)}` : undefined,
      meter:
        isNumber(cumulative) && isNumber(target) && target > 0
          ? Math.min(1, Math.max(0, cumulative / target))
          : undefined,
    },
    {
      key: "runtime",
      label: "Run time",
      value: isNumber(metadata.duration_sec) ? formatDuration(metadata.duration_sec) : MISSING,
    },
    {
      key: "flags",
      label: "Quality flags",
      value: Array.isArray(flags) ? (flags.length === 0 ? "None" : `${flags.length} flagged`) : MISSING,
    },
  ];
}

export function getFieldCoverage(annotation) {
  const coverage = getMetadata(annotation).field_coverage;
  if (!coverage || typeof coverage !== "object") return null;
  const values = Object.values(coverage);
  if (values.length === 0) return null;
  return { supported: values.filter((value) => value === "supported").length, total: values.length };
}

export function getNameSource(annotation) {
  const metadata = getMetadata(annotation);
  const source = String(metadata.gene_name_source || "");
  const detail = String(metadata.gene_name_source_detail || "");
  if (!source && !detail) return null;
  let label = source || detail;
  if (/uniprot/i.test(`${source} ${detail}`)) label = "UniProt";
  else if (/ncbi|entrez/i.test(`${source} ${detail}`)) label = "NCBI Gene";
  return metadata.gene_name_confidence ? `${label} · ${metadata.gene_name_confidence}` : label;
}

export function getAnnotationNotes(annotation) {
  const notes = getAnnotationPayload(annotation).annotation_notes;
  return typeof notes === "string" ? notes.trim() : "";
}

export function getQualityFlags(annotation) {
  const flags = getMetadata(annotation).quality_flags;
  if (!Array.isArray(flags)) return [];
  return flags.map((flag) => (typeof flag === "string" ? flag : JSON.stringify(flag)));
}

export function getPaperMatch(paper) {
  const sources = Array.isArray(paper?.retrieval_sources) ? paper.retrieval_sources : [];
  const warnings = Array.isArray(paper?.warnings) ? paper.warnings : [];
  if (warnings.includes("name_only_match")) return { label: "Name only", tone: "warning" };
  const byLocus = sources.includes("locus");
  const byName = sources.includes("name");
  if (byLocus && byName) return { label: "Locus + name", tone: "success" };
  if (byLocus) return { label: "Locus", tone: "success" };
  if (byName) return { label: "Name", tone: "neutral" };
  return null;
}

export function getSelectedPapers(annotation) {
  const papers = getLiterature(annotation).selected_paper_summaries;
  if (!Array.isArray(papers)) return [];
  return papers
    .map((paper, index) => ({
      key: String(paper.pmc_id || paper.pmid || index),
      pmcId: paper.pmc_id ? String(paper.pmc_id) : null,
      pmid: paper.pmid ? String(paper.pmid) : null,
      title: paper.title || "Untitled paper",
      year: paper.year ?? null,
      score: isNumber(paper.score) ? paper.score : null,
      match: getPaperMatch(paper),
    }))
    .sort((a, b) => (b.score ?? -1) - (a.score ?? -1));
}

export function getOrganismOptions(matches) {
  const names = new Set();
  for (const match of matches || []) {
    if (match?.canonical_name) names.add(match.canonical_name);
  }
  return [...names].sort((a, b) => a.localeCompare(b));
}

export function filterMatchesByOrganism(matches, organism) {
  if (!organism) return matches ?? [];
  return (matches || []).filter((match) => match?.canonical_name === organism);
}
