import assert from "node:assert/strict";
import test from "node:test";

import { filterProfiles, groupProfilesBySpecies } from "./profileFilters.js";

const profiles = [
  {
    profile_id: "mtb-h37rv",
    canonical_name: "Mycobacterium tuberculosis H37Rv",
    species_name: "Mycobacterium tuberculosis",
    strain: "H37Rv",
    synonyms: ["Mtb"],
  },
  {
    profile_id: "ecoli-k12-mg1655",
    canonical_name: "Escherichia coli K-12 MG1655",
    species_name: "Escherichia coli",
    strain: "K-12 MG1655",
    species_synonyms: ["E. coli"],
  },
  {
    profile_id: "ecoli-bl21",
    canonical_name: "Escherichia coli BL21",
    species_name: "Escherichia coli",
    strain: "BL21",
  },
];

test("filterProfiles searches profile names identifiers strains and synonyms", () => {
  assert.deepEqual(
    filterProfiles(profiles, { query: "e. coli" }).map(
      (profile) => profile.profile_id,
    ),
    ["ecoli-k12-mg1655"],
  );

  assert.deepEqual(
    filterProfiles(profiles, { query: "h37" }).map(
      (profile) => profile.profile_id,
    ),
    ["mtb-h37rv"],
  );
});

test("groupProfilesBySpecies groups filtered rows by species name", () => {
  assert.deepEqual(groupProfilesBySpecies(profiles), [
    {
      speciesName: "Mycobacterium tuberculosis",
      profiles: [profiles[0]],
    },
    {
      speciesName: "Escherichia coli",
      profiles: [profiles[1], profiles[2]],
    },
  ]);
});
