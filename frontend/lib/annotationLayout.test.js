import assert from "node:assert/strict";
import test from "node:test";

import { isCompactValue, planAnnotationGrid, splitListValue } from "./annotationLayout.js";

const LONG = "Growth of cultured bloodstream forms is sensitive to Hesperadin (IC50 of 50 nM) (PMID: 19320832).";

function row(key, value) {
  return { key, label: key, value };
}

test("isCompactValue keeps flags, empty values, and short lists compact", () => {
  assert.equal(isCompactValue("True"), true);
  assert.equal(isCompactValue("False"), true);
  assert.equal(isCompactValue("No supported data"), true);
  assert.equal(isCompactValue("Mitosis, Cell cycle, Cytokinesis"), true);
  assert.equal(isCompactValue(LONG), false);
  assert.equal(isCompactValue("Essential in mice."), false);
  assert.equal(isCompactValue("Not essential (PMID: 1)"), false);
  assert.equal(isCompactValue("x".repeat(81)), false);
});

test("planAnnotationGrid leads with the first prose field and pairs the rest", () => {
  const plan = planAnnotationGrid([
    row("functional_category", "Mitosis, Cell cycle"),
    row("function", LONG),
    row("drug_susc_impact", LONG),
    row("infection_impact", LONG),
    row("essential_in_vitro", "True"),
  ]);
  assert.deepEqual(
    plan.tiles.map((tile) => [tile.row.key, tile.span, tile.lead]),
    [
      ["function", "full", true],
      ["drug_susc_impact", "half", false],
      ["infection_impact", "half", false],
    ],
  );
  assert.deepEqual(plan.compact.map((item) => item.key), ["functional_category", "essential_in_vitro"]);
});

test("planAnnotationGrid gives an unpaired last prose field the full width", () => {
  const spans = (count) =>
    planAnnotationGrid(Array.from({ length: count }, (_, index) => row(`f${index}`, LONG))).tiles.map(
      (tile) => tile.span,
    );
  assert.deepEqual(spans(0), []);
  assert.deepEqual(spans(1), ["full"]);
  assert.deepEqual(spans(2), ["full", "full"]);
  assert.deepEqual(spans(4), ["full", "half", "half", "full"]);
});

test("splitListValue splits comma lists", () => {
  assert.deepEqual(splitListValue("Mitosis, Cell cycle ,Cytokinesis"), ["Mitosis", "Cell cycle", "Cytokinesis"]);
  assert.deepEqual(splitListValue("Mitosis"), ["Mitosis"]);
});
