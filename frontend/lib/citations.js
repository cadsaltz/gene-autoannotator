const SEPARATOR = String.raw`\s*(?:[,;]|\band\b)\s*`;
const PMID = String.raw`\bPMIDs?\s*:?\s*\d+`;
// Bare IDs may only be listed inside a citation-only parenthetical; in prose each ID
// needs its own PMID prefix, so trailing numbers like "2009" or "12 genes" are not cited.
const PAREN_LIST = String.raw`\(\s*${PMID}(?:${SEPARATOR}(?:PMIDs?\s*:?\s*)?\d+)*\s*\)`;
const BARE_LIST = String.raw`${PMID}(?:${SEPARATOR}${PMID})*`;
const CITATION_PATTERN = new RegExp(`${PAREN_LIST}|${BARE_LIST}`, "gi");

export function splitCitations(text) {
  const source = text == null ? "" : String(text);
  const segments = [];
  let lastIndex = 0;
  for (const match of source.matchAll(CITATION_PATTERN)) {
    const before = source.slice(lastIndex, match.index);
    if (before) segments.push({ type: "text", value: before });
    for (const pmid of match[0].match(/\d+/g)) {
      segments.push({ type: "pmid", value: pmid });
    }
    lastIndex = match.index + match[0].length;
  }
  const rest = source.slice(lastIndex);
  if (rest) segments.push({ type: "text", value: rest });
  return segments;
}

export function getCitedPmids(...texts) {
  const ids = new Set();
  for (const text of texts) {
    for (const segment of splitCitations(text)) {
      if (segment.type === "pmid") ids.add(segment.value);
    }
  }
  return [...ids];
}

export function pubmedUrl(pmid) {
  return `https://pubmed.ncbi.nlm.nih.gov/${pmid}/`;
}

export function pmcUrl(pmcId) {
  const id = String(pmcId).replace(/^PMC/i, "");
  return `https://pmc.ncbi.nlm.nih.gov/articles/PMC${id}/`;
}
