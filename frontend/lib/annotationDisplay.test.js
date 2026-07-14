import assert from "node:assert/strict";
import test from "node:test";

import {
  getGeneratedFieldRows,
  getMetadataRows,
  getPmcIdsAnalyzed,
} from "./annotationDisplay.js";

const annotation = {
  result: {
    annotation: {
      gene_id: "Rv0001",
      name: "dnaA",
      function: "Initiates chromosomal replication.",
      functional_category: ["information pathways", "DNA replication"],
      drug_susc_impact: "",
      infection_impact: null,
      essential_in_vitro: true,
      essential_in_vivo: false,
      annotation_notes: "Five papers were analyzed; support is mixed.",
      annotation_metadata: {
        literature: {
          total_papers_retrieved: 18,
          papers_analyzed: 5,
          sections_analyzed: 9,
          cumulative_relevance: 3.42,
          pmc_ids_analyzed: ["123", "456"],
        },
        llm_usage: {
          known_input_tokens: 1200,
          known_output_tokens: 345,
          known_total_tokens: 1545,
        },
        quality_flags: ["limited_literature"],
        duration_sec: 125,
      },
    },
  },
};

test("getGeneratedFieldRows returns the required fields in order with fallbacks", () => {
  assert.deepEqual(getGeneratedFieldRows(annotation).map((row) => row.key), [
    "functional_category",
    "function",
    "drug_susc_impact",
    "infection_impact",
    "essential_in_vitro",
    "essential_in_vivo",
  ]);
  assert.equal(getGeneratedFieldRows(annotation)[0].value, "information pathways, DNA replication");
  assert.equal(getGeneratedFieldRows(annotation)[2].value, "No supported data");
  assert.equal(getGeneratedFieldRows(annotation)[3].value, "No supported data");
  assert.equal(getGeneratedFieldRows(annotation)[4].value, "True");
  assert.equal(getGeneratedFieldRows(annotation)[5].value, "False");
});

test("getGeneratedFieldRows marks ortholog-derived fields from field_provenance", () => {
  const withOrtholog = {
    result: {
      annotation: {
        function: "Octanoyltransferase activity in M. orygis.",
        functional_category: ["cell wall"],
        drug_susc_impact: null,
        infection_impact: null,
        essential_in_vitro: null,
        essential_in_vivo: null,
        annotation_metadata: {
          field_provenance: {
            function: "ortholog_derived",
          },
          ortholog_fields: {
            function: {
              value: "Octanoyltransferase activity in M. orygis.",
              source_organism: "Mycobacterium orygis",
              source_gene_id: "MO_000001",
              identity: 0.62,
            },
          },
        },
      },
    },
  };

  const rows = getGeneratedFieldRows(withOrtholog);
  const functionRow = rows.find((row) => row.key === "function");
  const categoryRow = rows.find((row) => row.key === "functional_category");

  assert.equal(functionRow.orthologDerived, true);
  assert.equal(categoryRow.orthologDerived, false);
  // Same text as canonical value — show source chip only, not a duplicate paragraph.
  assert.equal(functionRow.orthologBlock.value, null);
  assert.ok(functionRow.orthologBlock.sourceLabel.includes("MO_000001"));
});

test("getMetadataRows extracts requested metadata fields", () => {
  const rows = getMetadataRows(annotation);

  assert.deepEqual(rows.map((row) => row.key), [
    "annotation_notes",
    "total_papers",
    "papers_analyzed",
    "sections_analyzed",
    "cumulative_relevance",
    "quality_flags",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "duration",
  ]);
  assert.equal(rows[0].value, "Five papers were analyzed; support is mixed.");
  assert.equal(rows[1].value, "18");
  assert.equal(rows[5].value, "limited_literature");
  assert.equal(rows[6].value, "1200");
  assert.equal(rows[7].value, "345");
  assert.equal(rows[8].value, "1545");
  assert.equal(rows[9].value, "2m 5s");
});

test("getPmcIdsAnalyzed returns analyzed PMC IDs", () => {
  assert.deepEqual(getPmcIdsAnalyzed(annotation), ["123", "456"]);
});

test("getGeneratedFieldRows surfaces ortholog block when both values present", () => {
  const withBoth = {
    result: {
      annotation: {
        function: "target function",
        annotation_metadata: {
          field_provenance: { function: "target_plus_ortholog" },
          ortholog_fields: {
            function: {
              value: "ortholog function",
              source_organism: "Mycobacterium orygis",
              source_gene_id: "MO_000001",
              source_gene_name: "octT",
              identity: 0.62,
            },
          },
        },
      },
    },
  };

  const rows = getGeneratedFieldRows(withBoth);
  const functionRow = rows.find((row) => row.key === "function");
  assert.equal(functionRow.value, "target function");
  assert.equal(functionRow.orthologDerived, true);
  assert.equal(functionRow.orthologBlock.value, "ortholog function");
  assert.ok(functionRow.orthologBlock.sourceLabel.includes("MO_000001"));
  assert.ok(functionRow.orthologBlock.sourceLabel.includes("62%"));
});

test("getGeneratedFieldRows leaves orthologBlock null without ortholog_fields", () => {
  const targetOnly = {
    result: { annotation: { function: "target only", annotation_metadata: {} } },
  };
  const row = getGeneratedFieldRows(targetOnly).find((r) => r.key === "function");
  assert.equal(row.orthologBlock, null);
  assert.equal(row.orthologDerived, false);
});
