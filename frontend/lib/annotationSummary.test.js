import assert from "node:assert/strict";
import test from "node:test";

import {
  filterMatchesByOrganism,
  getAnnotationNotes,
  getFieldCoverage,
  getNameSource,
  getOrganismOptions,
  getPaperMatch,
  getQualityFlags,
  getSelectedPapers,
  getStatCells,
} from "./annotationSummary.js";

function annotationWith(metadata = {}, extra = {}) {
  return {
    generated_at: "2026-05-27T16:54:00Z",
    result: { annotation: { annotation_notes: "  Twelve papers.  ", annotation_metadata: metadata, ...extra } },
  };
}

const LITERATURE = {
  papers_analyzed: 12,
  total_papers_retrieved: 37,
  sections_analyzed: 22,
  cumulative_relevance: 6.961,
  target_relevance: 9,
  selected_paper_summaries: [
    { pmc_id: "1", pmid: "11", score: 0.5, title: "Low", year: 2009, retrieval_sources: ["name"], warnings: ["name_only_match"] },
    { pmc_id: "2", pmid: "22", score: 0.948, title: "High", year: 2021, retrieval_sources: ["locus", "name"], warnings: [] },
  ],
};

test("getStatCells summarises the run", () => {
  const cells = getStatCells(
    annotationWith({ literature: LITERATURE, duration_sec: 486.2, quality_flags: [] }),
    { locale: "en-US", timeZone: "UTC" },
  );
  const byKey = Object.fromEntries(cells.map((cell) => [cell.key, cell]));
  assert.deepEqual(cells.map((cell) => cell.key), ["generated", "papers", "sections", "relevance", "runtime", "flags"]);
  assert.equal(byKey.generated.value, "May 27, 2026");
  assert.equal(byKey.papers.value, "12");
  assert.equal(byKey.papers.detail, "of 37 retrieved");
  assert.equal(byKey.sections.value, "22");
  assert.equal(byKey.relevance.value, "6.96");
  assert.equal(byKey.relevance.detail, "/ 9.0");
  assert.ok(Math.abs(byKey.relevance.meter - 6.961 / 9) < 1e-9);
  assert.equal(byKey.runtime.value, "8m 6s");
  assert.equal(byKey.flags.value, "None");
});

test("getStatCells shows a dash for missing values", () => {
  const cells = getStatCells({ result: {} });
  for (const cell of cells) assert.equal(cell.value, "—", cell.key);
  assert.equal(cells.find((cell) => cell.key === "relevance").meter, undefined);
});

test("getStatCells counts quality flags", () => {
  const cells = getStatCells(annotationWith({ quality_flags: ["low_coverage", "conflict"] }));
  assert.equal(cells.find((cell) => cell.key === "flags").value, "2 flagged");
});

test("getFieldCoverage counts supported fields", () => {
  assert.deepEqual(getFieldCoverage(annotationWith({ field_coverage: { a: "supported", b: "unsupported" } })), {
    supported: 1,
    total: 2,
  });
  assert.equal(getFieldCoverage(annotationWith({})), null);
});

test("getNameSource names the database and confidence", () => {
  assert.equal(
    getNameSource(
      annotationWith({
        gene_name_source: "cache",
        gene_name_source_detail: "Cached uniprot: https://rest.uniprot.org/uniprotkb/search",
        gene_name_confidence: "clear",
      }),
    ),
    "UniProt · clear",
  );
  assert.equal(getNameSource(annotationWith({ gene_name_source: "ncbi" })), "NCBI Gene");
  assert.equal(getNameSource(annotationWith({ gene_name_source: "manual" })), "manual");
  assert.equal(getNameSource(annotationWith({})), null);
});

test("notes and quality flags", () => {
  assert.equal(getAnnotationNotes(annotationWith({})), "Twelve papers.");
  assert.equal(getAnnotationNotes({}), "");
  assert.deepEqual(getQualityFlags(annotationWith({ quality_flags: ["a", { code: "b" }] })), ["a", '{"code":"b"}']);
  assert.deepEqual(getQualityFlags(annotationWith({})), []);
});

test("getPaperMatch labels how a paper was found", () => {
  assert.deepEqual(getPaperMatch({ retrieval_sources: ["locus", "name"], warnings: [] }), {
    label: "Locus + name",
    tone: "success",
  });
  assert.deepEqual(getPaperMatch({ retrieval_sources: ["locus"] }), { label: "Locus", tone: "success" });
  assert.deepEqual(getPaperMatch({ retrieval_sources: ["name"], warnings: [] }), { label: "Name", tone: "neutral" });
  assert.deepEqual(getPaperMatch({ retrieval_sources: ["name"], warnings: ["name_only_match"] }), {
    label: "Name only",
    tone: "warning",
  });
  assert.equal(getPaperMatch({}), null);
});

test("getSelectedPapers sorts by relevance", () => {
  const papers = getSelectedPapers(annotationWith({ literature: LITERATURE }));
  assert.deepEqual(papers.map((paper) => paper.title), ["High", "Low"]);
  assert.deepEqual(papers[0], {
    key: "2",
    pmcId: "2",
    pmid: "22",
    title: "High",
    year: 2021,
    score: 0.948,
    match: { label: "Locus + name", tone: "success" },
  });
  assert.deepEqual(getSelectedPapers(annotationWith({})), []);
});

test("organism filter", () => {
  const matches = [
    { id: 1, canonical_name: "Trypanosoma cruzi CL Brener" },
    { id: 2, canonical_name: "Leishmania major Friedlin" },
    { id: 3, canonical_name: "Trypanosoma cruzi CL Brener" },
    { id: 4 },
  ];
  assert.deepEqual(getOrganismOptions(matches), ["Leishmania major Friedlin", "Trypanosoma cruzi CL Brener"]);
  assert.deepEqual(filterMatchesByOrganism(matches, "Leishmania major Friedlin").map((m) => m.id), [2]);
  assert.equal(filterMatchesByOrganism(matches, ""), matches);
  assert.deepEqual(filterMatchesByOrganism(undefined, ""), []);
  assert.deepEqual(filterMatchesByOrganism(null, ""), []);
});
