const PMID_LIST = String.raw`\bPMIDs?\s*:?\s*\d+(?:\s*(?:[,;]|\band\b)\s*(?:PMIDs?\s*:?\s*)?\d+)*`;
// A parenthetical holding only citations is consumed whole; otherwise only the PMID text is.
const CITATION_PATTERN = new RegExp(String.raw`\(\s*${PMID_LIST}\s*\)|${PMID_LIST}`, "gi");

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
