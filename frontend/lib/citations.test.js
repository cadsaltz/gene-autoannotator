import assert from "node:assert/strict";
import test from "node:test";

import { getCitedPmids, pmcUrl, pubmedUrl, splitCitations } from "./citations.js";

test("splitCitations turns parenthesised PMIDs into citation segments", () => {
  assert.deepEqual(splitCitations("kinetoplast duplication (PMID: 30897087); coordinates mitosis"), [
    { type: "text", value: "kinetoplast duplication " },
    { type: "pmid", value: "30897087" },
    { type: "text", value: "; coordinates mitosis" },
  ]);
});

test("splitCitations expands lists of PMIDs", () => {
  assert.deepEqual(
    splitCitations("(PMID: 1, 22) and (PMIDs: 3; PMID: 4)").filter((s) => s.type === "pmid").map((s) => s.value),
    ["1", "22", "3", "4"],
  );
});

test("splitCitations finds bare PMIDs inside prose and keeps the surrounding text", () => {
  assert.deepEqual(splitCitations("(PMID: 34128702 reports false, while PMID: 19320832 reports true)"), [
    { type: "text", value: "(" },
    { type: "pmid", value: "34128702" },
    { type: "text", value: " reports false, while " },
    { type: "pmid", value: "19320832" },
    { type: "text", value: " reports true)" },
  ]);
  assert.deepEqual(splitCitations("the experimental evidence from PMID: 19320832."), [
    { type: "text", value: "the experimental evidence from " },
    { type: "pmid", value: "19320832" },
    { type: "text", value: "." },
  ]);
});

test("splitCitations expands bare lists joined by commas and 'and'", () => {
  assert.deepEqual(splitCitations("PMID: 1, 2 and 3"), [
    { type: "pmid", value: "1" },
    { type: "pmid", value: "2" },
    { type: "pmid", value: "3" },
  ]);
  assert.deepEqual(splitCitations("see PMIDs 4; 5 and others"), [
    { type: "text", value: "see " },
    { type: "pmid", value: "4" },
    { type: "pmid", value: "5" },
    { type: "text", value: " and others" },
  ]);
});

test("splitCitations leaves plain text alone", () => {
  assert.deepEqual(splitCitations("No citations here."), [{ type: "text", value: "No citations here." }]);
  assert.deepEqual(splitCitations(""), []);
  assert.deepEqual(splitCitations(null), []);
});

test("getCitedPmids counts distinct papers across texts", () => {
  assert.deepEqual(getCitedPmids("a (PMID: 19320832)", "b (PMID: 19320832) c (PMID: 30897087)"), [
    "19320832",
    "30897087",
  ]);
});

test("getCitedPmids covers parenthetical and bare citations in a real annotation", () => {
  const fn =
    "involved in mitotic spindle assembling and chromosome segregation; appears to play a role during the initiation of kinetoplast duplication (PMID: 30897087); coordinates events associated with mitosis and cytokinesis; phosphorylates histone H3 (PMID: 19320832); cell cycle control; phosphorylation of TbH3 and TbH2B (PMID: 19320832)";
  const drug = "Growth of cultured bloodstream forms is sensitive to Hesperadin (IC50 of 50 nM) (PMID: 19320832).";
  const infection =
    "Essential contribution to infection (demonstrated by conditional knockdown in infected mice) (PMID: 19320832).";
  const notes =
    "Twelve papers were analyzed to generate this annotation. The literature base is moderately strong, with several papers detailing AUK1's role in cell division and infection.  Fields related to essentiality were populated based on experimental evidence; the conflicting reports regarding in vitro essentiality (PMID: 34128702 reports false, while PMID: 19320832 reports true) were resolved by prioritizing the experimental evidence from PMID: 19320832.  Fields related to function were synthesized from multiple sources. The following fields remain unknown due to insufficient evidence: functional_category (in some instances), drug_susc_impact, and infection_impact.  A limitation is the varying levels of detail provided across the analyzed papers.";
  assert.deepEqual(getCitedPmids(fn, drug, infection, notes), ["30897087", "19320832", "34128702"]);
});

test("NCBI links", () => {
  assert.equal(pubmedUrl("19320832"), "https://pubmed.ncbi.nlm.nih.gov/19320832/");
  assert.equal(pmcUrl("8550152"), "https://pmc.ncbi.nlm.nih.gov/articles/PMC8550152/");
  assert.equal(pmcUrl("PMC8550152"), "https://pmc.ncbi.nlm.nih.gov/articles/PMC8550152/");
});
