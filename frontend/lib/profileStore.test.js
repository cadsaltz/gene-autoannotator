import assert from "node:assert/strict";
import test from "node:test";

import {
  buildProfilePayload,
  canEnableOrthologAllowed,
  profileToForm,
  resolveProfileFieldsForDisplay,
  sanitizeCustomFieldsForPayload,
  sanitizeDefaultFieldOrthologForPayload,
  splitLines,
} from "./profileStore.js";

test("splitLines trims empty profile list entries", () => {
  assert.deepEqual(splitLines("abc\n\n def "), ["abc", "def"]);
});

test("buildProfilePayload serializes profile form fields", () => {
  assert.deepEqual(
    buildProfilePayload({
      profileId: "custom-profile",
      canonicalName: "Custom organism",
      speciesName: "Custom organism",
      strain: "Lab A",
      synonyms: "custom org",
      speciesSynonyms: "",
      strainSynonyms: "lab a",
      locusRegex: "^CUS_\\d+$",
      searchTerms: "Custom organism",
      targetPatterns: "Custom organism",
      offTargetPatterns: "Other organism",
      excludedSpeciesPatterns: "",
      keggLocusRegex: "",
      defaultFieldOrtholog: {
        function: true,
        functional_category: false,
      },
    }),
    {
      profile_id: "custom-profile",
      canonical_name: "Custom organism",
      species_name: "Custom organism",
      strain: "Lab A",
      synonyms: ["custom org"],
      species_synonyms: [],
      strain_synonyms: ["lab a"],
      locus_regex: "^CUS_\\d+$",
      search_terms: ["Custom organism"],
      target_patterns: ["Custom organism"],
      off_target_patterns: ["Other organism"],
      excluded_species_patterns: [],
      kegg_organism_code: null,
      kegg_locus_regex: null,
      custom_fields: [],
      default_field_ortholog: {
        function: false,
        functional_category: false,
      },
      go_resolution_enabled: false,
    },
  );
});

test("buildProfilePayload enables GO resolution when checked", () => {
  assert.equal(
    buildProfilePayload({ goResolutionEnabled: true }).go_resolution_enabled,
    true,
  );
});

test("profileToForm defaults GO resolution off and restores enabled profiles", () => {
  assert.equal(profileToForm({}).goResolutionEnabled, false);
  assert.equal(
    profileToForm({ go_resolution_enabled: true }).goResolutionEnabled,
    true,
  );
});

test("sanitizeDefaultFieldOrthologForPayload clears ortholog without kegg code", () => {
  assert.deepEqual(
    sanitizeDefaultFieldOrthologForPayload(
      { function: true, functional_category: true },
      "",
    ),
    { function: false, functional_category: false },
  );
});

test("resolveProfileFieldsForDisplay merges defaults and custom fields", () => {
  const fields = resolveProfileFieldsForDisplay({
    kegg_organism_code: "mtu",
    default_field_ortholog: { functional_category: true },
    custom_fields: [
      {
        key: "virulence_factor",
        label: "Virulence factor",
        description: "Contribution to virulence.",
        ortholog_allowed: true,
      },
    ],
  });

  assert.equal(fields.length, 3);
  assert.equal(fields[0].key, "function");
  assert.equal(fields[0].isDefault, true);
  assert.equal(fields[1].key, "functional_category");
  assert.equal(fields[1].ortholog_allowed, true);
  assert.equal(fields[2].key, "virulence_factor");
  assert.equal(fields[2].isDefault, false);
});

test("sanitizeCustomFieldsForPayload clears ortholog_allowed without kegg code", () => {
  assert.deepEqual(
    sanitizeCustomFieldsForPayload(
      [{ key: "function", ortholog_allowed: true }],
      "",
    ),
    [{ key: "function", ortholog_allowed: false }],
  );
  assert.equal(canEnableOrthologAllowed("mtu"), true);
  assert.equal(canEnableOrthologAllowed(""), false);
});
