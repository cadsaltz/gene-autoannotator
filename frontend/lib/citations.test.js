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

test("NCBI links", () => {
  assert.equal(pubmedUrl("19320832"), "https://pubmed.ncbi.nlm.nih.gov/19320832/");
  assert.equal(pmcUrl("8550152"), "https://pmc.ncbi.nlm.nih.gov/articles/PMC8550152/");
  assert.equal(pmcUrl("PMC8550152"), "https://pmc.ncbi.nlm.nih.gov/articles/PMC8550152/");
});
