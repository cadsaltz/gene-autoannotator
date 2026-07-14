import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

const projectRoot = process.cwd();

async function readProjectFile(relativePath) {
  return readFile(path.join(projectRoot, relativePath), "utf8");
}

test("profiles page is reachable from the workbench navigation", async () => {
  const appShell = await readProjectFile("components/AppShell.js");

  assert.match(
    appShell,
    /const navItems = \[\s*\{ href: "\/", label: "Guide" \},\s*\{ href: "\/jobs", label: "Jobs" \},\s*\{ href: "\/fleet", label: "Fleet & Health" \},\s*\{ href: "\/profiles", label: "Profiles" \},\s*\{ href: "\/annotations", label: "Annotations" \},\s*\];/s,
  );
});

test("profiles route renders the profile workspace in the app shell", async () => {
  const route = await readProjectFile("app/profiles/page.js");

  assert.match(route, /import AppShell from "\.\.\/\.\.\/components\/AppShell";/);
  assert.match(route, /import ProfileWorkspace from "\.\.\/\.\.\/components\/ProfileWorkspace";/);
  assert.match(route, /title: "Profiles · Gene Autoannotator"/);
  assert.match(route, /<AppShell>\s*<ProfileWorkspace \/>\s*<\/AppShell>/s);
});

test("profile workspace supports editing all reusable profile fields", async () => {
  const workspace = await readProjectFile("components/ProfileWorkspace.js");

  assert.match(workspace, /"use client";/);
  assert.match(
    workspace,
    /import \{\s*createProfile,\s*deleteProfile,\s*getProfiles,\s*updateProfile,\s*\} from "\.\.\/lib\/api";/s,
  );
  assert.match(workspace, /import \{ buildProfilePayload, profileToForm, resolveProfileFieldsForDisplay/);

  for (const field of [
    "profileId",
    "canonicalName",
    "speciesName",
    "strain",
    "synonyms",
    "speciesSynonyms",
    "strainSynonyms",
    "locusRegex",
    "searchTerms",
    "targetPatterns",
    "offTargetPatterns",
    "excludedSpeciesPatterns",
    "keggOrganismCode",
    "customFields",
    "defaultFieldOrtholog",
  ]) {
    assert.match(workspace, new RegExp(`\\b${field}\\b`));
  }

  assert.match(workspace, /getProfiles\(\)/);
  assert.match(workspace, /buildProfilePayload\(form\)/);
  assert.match(workspace, /updateProfile\(editingProfileId,/);
  assert.match(workspace, /createProfile\(payload\)/);
  assert.match(workspace, /deleteProfile\(profileId\)/);
  assert.doesNotMatch(workspace, /profile\.source === "builtin"/);
  assert.doesNotMatch(workspace, /PROFILE_SOURCE_FILTERS/);
  assert.doesNotMatch(workspace, /Built-in/);
});

test("resetting the profile form clears stale edit status text", async () => {
  const workspace = await readProjectFile("components/ProfileWorkspace.js");

  assert.match(
    workspace,
    /function resetForm\(\) \{\s*setForm\(emptyForm\);\s*setEditingProfileId\(""\);\s*setStatusMessage\(""\);\s*\}/s,
  );
  assert.match(workspace, /onClick=\{resetForm\}/);
});

test("profile detail cards include synonym fields", async () => {
  const workspace = await readProjectFile("components/ProfileWorkspace.js");

  assert.match(workspace, /\["Profile synonyms", profile\.synonyms\?\.join\(", "\)\]/);
  assert.match(workspace, /\["Species synonyms", profile\.species_synonyms\?\.join\(", "\)\]/);
  assert.match(workspace, /\["Strain synonyms", profile\.strain_synonyms\?\.join\(", "\)\]/);
});

test("profile workspace describes local file storage", async () => {
  const workspace = await readProjectFile("components/ProfileWorkspace.js");

  assert.match(workspace, /data\/profiles/);
  assert.match(workspace, /PROFILES_DIR/);
  assert.match(workspace, /MongoDB is not[\s\S]*used for organism profiles/);
});

test("profile workspace mounts the regex helper under the form", async () => {
  const workspace = await readProjectFile("components/ProfileWorkspace.js");

  assert.match(workspace, /import RegexHelper from "\.\/RegexHelper";/);
  assert.match(
    workspace,
    /<RegexHelper onApply=\{\(regex\) => updateForm\("locusRegex", regex\)\} \/>/,
  );
});

test("profile workspace avoids loading-only submit hydration mismatches", async () => {
  const workspace = await readProjectFile("components/ProfileWorkspace.js");

  assert.match(workspace, /const \[isLoading, setIsLoading\] = useState\(false\);/);
  assert.match(workspace, /disabled=\{isSaving \|\| isLoading\}/);
});

test("available profiles are searchable and grouped by species", async () => {
  const workspace = await readProjectFile("components/ProfileWorkspace.js");

  assert.match(
    workspace,
    /import \{\s*filterProfiles,\s*groupProfilesBySpecies,\s*\} from "\.\.\/lib\/profileFilters";/s,
  );
  assert.match(workspace, /placeholder="Search profile ID, organism, strain, or synonym"/);
  assert.doesNotMatch(workspace, /PROFILE_SOURCE_FILTERS/);
  assert.match(workspace, /groupProfilesBySpecies\(visibleProfiles\)/);
});

test("profile rows are compact and expand details one at a time", async () => {
  const workspace = await readProjectFile("components/ProfileWorkspace.js");

  assert.match(workspace, /const \[expandedProfileId, setExpandedProfileId\] = useState\(""\);/);
  assert.match(workspace, /expandedProfileId === profile\.profile_id/);
  assert.match(workspace, /setExpandedProfileId\(isExpanded \? "" : profile\.profile_id\)/);
  assert.match(workspace, /ProfileFieldsDisplay profile=\{profile\}/);
  assert.match(workspace, /resolveProfileFieldsForDisplay/);
});
