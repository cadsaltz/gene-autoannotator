import assert from "node:assert/strict";
import test from "node:test";

import * as annotationDisplay from "./annotationDisplay.js";
import { resolveProfileFieldsForDisplay } from "./profileStore.js";

const {
  getGeneratedFieldRows,
  getMetadataRows,
  getPmcIdsAnalyzed,
} = annotationDisplay;

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

test("getGeneratedFieldRows shows only current profile fields even if annotation has others", () => {
  const profileFields = resolveProfileFieldsForDisplay({
    kegg_organism_code: "mtu",
    custom_fields: [
      {
        key: "drug_susc_impact",
        label: "Drug susceptibility impact",
      },
      {
        key: "infection_impact",
        label: "Infection impact",
      },
    ],
  });

  const rows = getGeneratedFieldRows(annotation, profileFields);
  assert.deepEqual(rows.map((row) => row.key), [
    "function",
    "functional_category",
    "drug_susc_impact",
    "infection_impact",
  ]);
  assert.equal(rows.find((row) => row.key === "essential_in_vitro"), undefined);
  assert.equal(rows.find((row) => row.key === "essential_in_vivo"), undefined);
  assert.equal(
    rows.find((row) => row.key === "drug_susc_impact").value,
    "No supported data",
  );
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
  assert.equal(functionRow.orthologOnly, true);
  assert.equal(categoryRow.orthologDerived, false);
  assert.equal(categoryRow.orthologOnly, false);
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
  assert.equal(functionRow.orthologOnly, false);
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

test("GO helpers read target and ortholog terms from their separate stores", () => {
  assert.equal(typeof annotationDisplay.getTargetGoTerms, "function");
  assert.equal(typeof annotationDisplay.getOrthologGoTerms, "function");
  const withGoTerms = {
    result: {
      annotation: {
        go_terms: [{ id: "GO:0006355", name: "regulation of DNA-templated transcription" }],
        annotation_metadata: {
          ortholog_go_terms: [{ id: "GO:0006260", name: "DNA replication" }],
        },
      },
    },
  };

  assert.deepEqual(annotationDisplay.getTargetGoTerms(withGoTerms), [
    { id: "GO:0006355", name: "regulation of DNA-templated transcription" },
  ]);
  assert.deepEqual(annotationDisplay.getOrthologGoTerms(withGoTerms), [
    { id: "GO:0006260", name: "DNA replication" },
  ]);
});

test("GO helpers return empty lists when terms are absent or malformed", () => {
  assert.equal(typeof annotationDisplay.getTargetGoTerms, "function");
  assert.equal(typeof annotationDisplay.getOrthologGoTerms, "function");
  assert.deepEqual(annotationDisplay.getTargetGoTerms(annotation), []);
  assert.deepEqual(annotationDisplay.getOrthologGoTerms(annotation), []);
  assert.deepEqual(
    annotationDisplay.getTargetGoTerms({
      result: { annotation: { go_terms: "GO:0006260" } },
    }),
    [],
  );
});

test("formatGoTermLabel includes only GO id and name", () => {
  assert.equal(typeof annotationDisplay.formatGoTermLabel, "function");
  const term = {
    id: "GO:0006260",
    name: "DNA replication",
    agreement: "3/3",
    confidence: 0.98,
    votes: [{ model: "ranker-a", selected: true }],
  };

  const label = annotationDisplay.formatGoTermLabel(term);
  assert.equal(label, "GO:0006260 — DNA replication");
  assert.equal(label.includes("3/3"), false);
  assert.equal(label.includes("0.98"), false);
  assert.equal(label.includes("ranker-a"), false);
});

test("hasOrthologColumn gates on actual ortholog content, not merely ran===true", () => {
  assert.equal(typeof annotationDisplay.hasOrthologColumn, "function");
  const wrapMetadata = (metadata) => ({
    result: { annotation: { annotation_metadata: metadata } },
  });

  assert.equal(annotationDisplay.hasOrthologColumn(annotation), false);

  // A pass can run and still contribute nothing (no papers, no fields
  // filled) — that must NOT show an empty Ortholog column.
  assert.equal(
    annotationDisplay.hasOrthologColumn(wrapMetadata({ ortholog_pass: { ran: true } })),
    false,
  );
  assert.equal(
    annotationDisplay.hasOrthologColumn(
      wrapMetadata({
        ortholog_pass: { ran: true },
        ortholog_fields: {},
        ortholog_go_terms: [],
      }),
    ),
    false,
  );

  assert.equal(
    annotationDisplay.hasOrthologColumn(
      wrapMetadata({
        ortholog_pass: { ran: true },
        ortholog_fields: { function: { value: "ortholog" } },
      }),
    ),
    true,
  );
  assert.equal(
    annotationDisplay.hasOrthologColumn(
      wrapMetadata({ ortholog_fields: { function: { value: "ortholog" } } }),
    ),
    true,
  );
  assert.equal(
    annotationDisplay.hasOrthologColumn(
      wrapMetadata({ ortholog_go_terms: [{ id: "GO:0006260", name: "DNA replication" }] }),
    ),
    true,
  );
  assert.equal(
    annotationDisplay.hasOrthologColumn(wrapMetadata({ ortholog_pass: { ran: false } })),
    false,
  );
});
