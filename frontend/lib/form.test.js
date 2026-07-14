import assert from "node:assert/strict";
import test from "node:test";

import {
  buildBatchPayload,
  buildJobPayload,
  buildJobPrefillHref,
  formatElapsedSeconds,
  formatJobElapsed,
  parseGeneFileName,
  parseGeneListText,
  readGeneFile,
} from "./form.js";

test("buildJobPayload omits empty optional fields and maps option names", () => {
  assert.deepEqual(
    buildJobPayload({
      profile: "mtb-h37rv",
      organism: "",
      strain: "",
      locus: "Rv0001",
      name: "",
      allowOnlineNameLookup: false,
      refreshGeneNameCache: true,
      cacheSuppliedName: false,
    }),
    {
      profile: "mtb-h37rv",
      locus: "Rv0001",
      allow_online_name_lookup: false,
      refresh_gene_name_cache: true,
      cache_supplied_name: false,
      allow_ortholog_fallback: false,
    },
  );
});

test("buildJobPayload supports name-only custom organism jobs", () => {
  assert.deepEqual(
    buildJobPayload({
      profile: "",
      organism: "Custom bacterium",
      strain: "Lab A",
      locus: "",
      name: "abc1",
      allowOnlineNameLookup: true,
      refreshGeneNameCache: false,
      cacheSuppliedName: false,
      locusRegex: "",
      searchTerms: "Custom bacterium\nC. bacterium",
      targetPatterns: "Custom bacterium",
      offTargetPatterns: "",
      excludedSpeciesPatterns: "",
    }),
    {
      organism: "Custom bacterium",
      strain: "Lab A",
      name: "abc1",
      allow_online_name_lookup: true,
      refresh_gene_name_cache: false,
      cache_supplied_name: false,
      allow_ortholog_fallback: false,
      search_terms: ["Custom bacterium", "C. bacterium"],
      target_patterns: ["Custom bacterium"],
    },
  );
});

test("buildJobPayload omits stale custom organism fields when a profile is selected", () => {
  assert.deepEqual(
    buildJobPayload({
      profile: "mtb-h37rv",
      organism: "Stale organism",
      strain: "Stale strain",
      locus: "Rv0001",
      name: "dnaA",
      allowOnlineNameLookup: true,
      refreshGeneNameCache: false,
      cacheSuppliedName: true,
      locusRegex: "^STALE_\\d+$",
      searchTerms: "stale search",
      targetPatterns: "stale target",
      offTargetPatterns: "stale off target",
      excludedSpeciesPatterns: "stale excluded",
    }),
    {
      profile: "mtb-h37rv",
      locus: "Rv0001",
      name: "dnaA",
      allow_online_name_lookup: true,
      refresh_gene_name_cache: false,
      cache_supplied_name: true,
      allow_ortholog_fallback: false,
    },
  );
});

test("buildJobPrefillHref creates a jobs URL from annotation identity", () => {
  assert.equal(
    buildJobPrefillHref({
      profile_id: "mtb-h37rv",
      normalized_locus: "Rv0001",
      gene_name: "dnaA",
    }),
    "/jobs?profile=mtb-h37rv&locus=Rv0001&name=dnaA",
  );
});

test("formatElapsedSeconds renders compact elapsed durations", () => {
  assert.equal(formatElapsedSeconds(5), "5s");
  assert.equal(formatElapsedSeconds(65), "1m 5s");
  assert.equal(formatElapsedSeconds(3661), "1h 1m");
});

test("formatJobElapsed shows a placeholder before a job starts", () => {
  assert.equal(
    formatJobElapsed({
      status: "queued",
      created_at: "2026-05-27T10:00:00.000Z",
      started_at: null,
      finished_at: null,
    }, Date.parse("2026-05-27T10:05:00.000Z")),
    "--",
  );
});

test("formatJobElapsed counts running jobs from started_at", () => {
  assert.equal(
    formatJobElapsed({
      status: "running",
      created_at: "2026-05-27T09:55:00.000Z",
      started_at: "2026-05-27T10:00:00.000Z",
      finished_at: null,
    }, Date.parse("2026-05-27T10:02:05.000Z")),
    "2m 5s",
  );
});

test("formatJobElapsed stops counting when a job finishes", () => {
  assert.equal(
    formatJobElapsed({
      status: "completed",
      created_at: "2026-05-27T09:55:00.000Z",
      started_at: "2026-05-27T10:00:00.000Z",
      finished_at: "2026-05-27T10:03:01.000Z",
    }, Date.parse("2026-05-27T11:00:00.000Z")),
    "3m 1s",
  );
});

test("parseGeneListText splits newlines and ignores comments", () => {
  assert.deepEqual(parseGeneListText("Rv0001\n# skip\nRv0002"), [
    { input: "Rv0001" },
    { input: "Rv0002" },
  ]);
});

test("parseGeneListText parses two-column csv", () => {
  assert.deepEqual(parseGeneListText("locus,name\nRv0001,dnaA"), [
    { locus: "Rv0001", name: "dnaA" },
  ]);
});

test("parseGeneFileName rejects excel", () => {
  assert.throws(
    () => parseGeneFileName("genes.xlsx"),
    /txt, \.csv, or \.tsv/,
  );
});

test("buildBatchPayload maps entries and options", () => {
  assert.deepEqual(
    buildBatchPayload(
      {
        profile: "mtb-h37rv",
        allowOnlineNameLookup: false,
        refreshGeneNameCache: false,
        cacheSuppliedName: false,
      },
      [{ input: "Rv0001" }],
    ),
    {
      profile: "mtb-h37rv",
      entries: [{ input: "Rv0001" }],
      allow_online_name_lookup: false,
      refresh_gene_name_cache: false,
      cache_supplied_name: false,
      allow_ortholog_fallback: false,
    },
  );
});

test("readGeneFile parses allowed text files", async () => {
  const file = new File(["Rv0001\nRv0002"], "genes.txt", { type: "text/plain" });
  assert.deepEqual(await readGeneFile(file), [
    { input: "Rv0001" },
    { input: "Rv0002" },
  ]);
});

test("buildJobPayload includes allow_ortholog_fallback and override when enabled", () => {
  const payload = buildJobPayload({
    profile: "mtb-h37rv",
    locus: "Rv0001",
    allowOrthologFallback: true,
    orthologProfile: "mory",
    orthologLocus: "MO_000001",
    orthologName: "dnaA",
  });
  assert.equal(payload.allow_ortholog_fallback, true);
  assert.deepEqual(payload.ortholog_override, {
    profile_id: "mory",
    locus: "MO_000001",
    name: "dnaA",
  });
});

test("buildJobPayload includes profile-only override when locus is blank", () => {
  const payload = buildJobPayload({
    profile: "mtb-h37rv",
    locus: "Rv0001",
    allowOrthologFallback: true,
    orthologProfile: "mory",
    orthologLocus: "",
  });
  assert.equal(payload.allow_ortholog_fallback, true);
  assert.deepEqual(payload.ortholog_override, {
    profile_id: "mory",
    locus: null,
    name: null,
  });
});

test("buildBatchPayload includes profile-only ortholog override", () => {
  const payload = buildBatchPayload(
    {
      profile: "mtb-h37rv",
      allowOrthologFallback: true,
      orthologProfile: "mory",
      orthologLocus: "MO_000001",
      orthologName: "dnaA",
    },
    [{ input: "Rv0001" }],
  );
  assert.equal(payload.allow_ortholog_fallback, true);
  assert.deepEqual(payload.ortholog_override, {
    profile_id: "mory",
    locus: null,
    name: null,
  });
});

test("buildJobPayload defaults fallback to false", () => {
  const payload = buildJobPayload({ profile: "mtb-h37rv", locus: "Rv0001" });
  assert.equal(payload.allow_ortholog_fallback, false);
  assert.equal(payload.ortholog_override, undefined);
});
