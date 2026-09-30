import assert from "node:assert/strict";
import test from "node:test";

import {
  getAnnotationStorageHealth,
  getStoredAnnotation,
  getStoredAnnotationVersions,
  searchStoredAnnotations,
} from "./annotationStore.js";

function makeDocument(overrides = {}) {
  return {
    _id: "mtb-h37rv:Rv0001",
    profile_id: "mtb-h37rv",
    canonical_name: "Mycobacterium tuberculosis H37Rv",
    species_name: "Mycobacterium tuberculosis",
    strain: "H37Rv",
    normalized_locus: "Rv0001",
    gene_name: "dnaA",
    generated_at: "2026-06-05T10:00:00Z",
    version_count: 1,
    current: {
      job_id: "job-current",
      output_path: "gen_json/gen_Rv0001.json",
      result: {
        annotation: {
          gene_id: "Rv0001",
          name: "dnaA",
          function: "Chromosomal replication initiator",
        },
      },
    },
    versions: [
      {
        version_id: "version-1",
        job_id: "job-older",
        generated_at: "2026-06-04T10:00:00Z",
        gene_name: "dnaA",
        result: { annotation: { gene_id: "Rv0001" } },
      },
    ],
    ...overrides,
  };
}

test("searchStoredAnnotations returns public summaries and escapes regex input", async () => {
  let receivedFilter;
  let receivedOptions;
  const collection = {
    find(filter, options) {
      receivedFilter = filter;
      receivedOptions = options;
      return {
        async toArray() {
          return [makeDocument()];
        },
      };
    },
  };

  const matches = await searchStoredAnnotations(collection, "Rv0001.*", 7);

  assert.deepEqual(receivedFilter, {
    search_text: { $regex: "Rv0001\\.\\*", $options: "i" },
  });
  assert.deepEqual(receivedOptions, { limit: 7 });
  assert.deepEqual(matches, [
    {
      id: "mtb-h37rv:Rv0001",
      profile_id: "mtb-h37rv",
      canonical_name: "Mycobacterium tuberculosis H37Rv",
      species_name: "Mycobacterium tuberculosis",
      strain: "H37Rv",
      normalized_locus: "Rv0001",
      gene_name: "dnaA",
      generated_at: "2026-06-05T10:00:00Z",
      version_count: 1,
    },
  ]);
});

test("searchStoredAnnotations returns no matches for blank queries", async () => {
  const collection = {
    find() {
      throw new Error("blank searches should not query MongoDB");
    },
  };

  assert.deepEqual(await searchStoredAnnotations(collection, "   "), []);
});

test("getStoredAnnotation includes job details only when requested", async () => {
  const collection = {
    async findOne(filter) {
      assert.deepEqual(filter, { _id: "mtb-h37rv:Rv0001" });
      return makeDocument();
    },
  };

  const annotation = await getStoredAnnotation(collection, "mtb-h37rv:Rv0001", {
    includeJobDetails: true,
  });

  assert.equal(annotation.id, "mtb-h37rv:Rv0001");
  assert.equal(annotation.job_id, "job-current");
  assert.equal(annotation.output_path, "gen_json/gen_Rv0001.json");
  assert.equal(annotation.result.annotation.function, "Chromosomal replication initiator");
});

test("getStoredAnnotation omits job details by default", async () => {
  const collection = {
    async findOne() {
      return makeDocument();
    },
  };

  const annotation = await getStoredAnnotation(collection, "mtb-h37rv:Rv0001");

  assert.equal("job_id" in annotation, false);
  assert.equal("output_path" in annotation, false);
  assert.equal(annotation.result.annotation.function, "Chromosomal replication initiator");
});

test("getStoredAnnotation redacts api_key values in the result", async () => {
  const collection = {
    async findOne() {
      return makeDocument({
        current: {
          job_id: "job-current",
          output_path: "gen_json/gen_Rv0001.json",
          result: { sources: ["https://eutils.test/efetch?id=1&api_key=secret123"] },
        },
      });
    },
  };

  const annotation = await getStoredAnnotation(collection, "mtb-h37rv:Rv0001");

  assert.deepEqual(annotation.result.sources, ["https://eutils.test/efetch?id=1&api_key=REDACTED"]);
});

test("getStoredAnnotationVersions returns older versions with job details when requested", async () => {
  const collection = {
    async findOne(filter, projection) {
      assert.deepEqual(filter, { _id: "mtb-h37rv:Rv0001" });
      assert.deepEqual(projection, { projection: { versions: 1 } });
      return makeDocument();
    },
  };

  const versions = await getStoredAnnotationVersions(collection, "mtb-h37rv:Rv0001", {
    includeJobDetails: true,
  });

  assert.deepEqual(versions, makeDocument().versions);
});

test("getStoredAnnotationVersions strips job details and redacts secrets by default", async () => {
  const collection = {
    async findOne() {
      return makeDocument({
        versions: [
          {
            version_id: "version-1",
            job_id: "job-older",
            output_path: "gen_json/old.json",
            generated_at: "2026-06-04T10:00:00Z",
            result: { note: "api_key=secret456" },
          },
        ],
      });
    },
  };

  const versions = await getStoredAnnotationVersions(collection, "mtb-h37rv:Rv0001");

  assert.deepEqual(versions, [
    {
      version_id: "version-1",
      generated_at: "2026-06-04T10:00:00Z",
      result: { note: "api_key=REDACTED" },
    },
  ]);
});

test("getAnnotationStorageHealth reports the Next server Mongo ping result", async () => {
  const health = await getAnnotationStorageHealth({
    databaseName: "gene_autoannotator",
    async ping() {
      return { ok: 1 };
    },
  });

  assert.deepEqual(health, {
    status: "ok",
    database: "gene_autoannotator",
    source: "next",
  });
});
