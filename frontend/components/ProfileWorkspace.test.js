import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

import { navItemsFor } from "../lib/navItems.js";

const projectRoot = process.cwd();

async function readProjectFile(relativePath) {
  return readFile(path.join(projectRoot, relativePath), "utf8");
}

test("profiles page is reachable from the workbench navigation", () => {
  for (const role of ["user", "admin"]) {
    assert.ok(
      navItemsFor({ role, status: "active" }).some(
        (item) => item.href === "/profiles" && item.label === "Profiles",
      ),
    );
  }
});

test("profiles route renders the profile workspace in the app shell", async () => {
  const route = await readProjectFile("app/profiles/page.js");

  assert.match(route, /import AppShell from "\.\.\/\.\.\/components\/AppShell";/);
  assert.match(route, /import ProfileWorkspace from "\.\.\/\.\.\/components\/ProfileWorkspace";/);
  assert.match(route, /title: "Profiles · Gene Autoannotator"/);
  assert.match(
    route,
    /<AppShell>\s*<ProfileWorkspace canEdit=\{user\?\.role === "admin"\} \/>\s*<\/AppShell>/s,
  );
});

test("profiles route redirects signed-out visitors and derives canEdit from the session", async () => {
  const route = await readProjectFile("app/profiles/page.js");

  assert.match(route, /import \{ redirect \} from "next\/navigation";/);
  assert.match(route, /import \{ getServerSession \} from "\.\.\/\.\.\/lib\/session";/);
  assert.match(route, /export default async function ProfilesPage\(\)/);
  assert.match(route, /const \{ user, reason \} = await getServerSession\(\);/);
  assert.match(
    route,
    /if \(!user && reason === "signed_out"\) \{\s*redirect\("\/login\?next=\/profiles"\);\s*\}/,
  );
});

const GATED_FORM =
  /\{canEdit \? \(\s*<section ref=\{formRef\}[\s\S]*?<\/form>\s*<\/section>\s*\) : null\}/;
const GATED_ROW_ACTIONS =
  /\{canEdit \? \(\s*<>\s*<button[\s\S]*?<\/>\s*\) : null\}/;

test("profile workspace defaults to read-only and gates the editor behind canEdit", async () => {
  const workspace = await readProjectFile("components/ProfileWorkspace.js");

  assert.match(workspace, /export default function ProfileWorkspace\(\{ canEdit = false \}\)/);

  const form = workspace.match(GATED_FORM)?.[0];
  assert.ok(form, "form section must be wrapped in {canEdit ? (...) : null}");
  for (const piece of [
    /<RegexHelper /,
    /<CustomFieldsEditor/,
    /onSubmit=\{handleSubmit\}/,
    /"New profile"/,
    /"Create profile"/,
    /"Update profile"/,
    /Cancel edit/,
  ]) {
    assert.match(form, piece);
  }

  const outsideForm = workspace.replace(GATED_FORM, "");
  assert.doesNotMatch(outsideForm, /<RegexHelper /);
  assert.doesNotMatch(outsideForm, /<CustomFieldsEditor/);
  assert.doesNotMatch(outsideForm, /New profile|Create profile/);
});

test("profile rows only offer edit and delete when canEdit", async () => {
  const workspace = await readProjectFile("components/ProfileWorkspace.js");

  const actions = workspace.match(GATED_ROW_ACTIONS)?.[0];
  assert.ok(actions, "row edit/delete buttons must be wrapped in {canEdit ? (<>...</>) : null}");
  assert.match(actions, /onClick=\{\(\) => startEditing\(profile\)\}/);
  assert.match(actions, /onClick=\{\(\) => handleDelete\(profile\.profile_id\)\}/);

  const outside = workspace.replace(GATED_FORM, "").replace(GATED_ROW_ACTIONS, "");
  assert.doesNotMatch(outside, /startEditing\(profile\)\}/);
  assert.doesNotMatch(outside, /handleDelete\(profile\.profile_id\)/);
  assert.match(outside, /\{isExpanded \? "Collapse" : "Expand"\}/);
  assert.match(outside, /<ProfileDetailList profile=\{profile\} \/>/);
});

test("read-only profile workspace swaps admin copy for a managed-by-admins note", async () => {
  const workspace = await readProjectFile("components/ProfileWorkspace.js");

  assert.match(workspace, /Profiles are managed by admins\./);
  assert.match(
    workspace,
    /\{canEdit \? "Manage reusable annotation targets" : "Browse reusable annotation targets"\}/,
  );
  assert.match(
    workspace,
    /\{canEdit \? \(\s*<div className="workbench-amber-bg[\s\S]*?Profile storage[\s\S]*?PROFILES_DIR[\s\S]*?<\/div>\s*\) : null\}/,
  );
  assert.doesNotMatch(workspace, /href=/);
});

test("read-only profile workspace still surfaces load errors", async () => {
  const workspace = await readProjectFile("components/ProfileWorkspace.js");

  assert.match(
    workspace,
    /\{!canEdit && statusMessage \? \(\s*<p[\s\S]*?\{statusMessage\}\s*<\/p>\s*\) : null\}/,
  );
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
    "keggLocusRegex",
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

test("profile workspace exposes GO resolution beside required annotation fields", async () => {
  const workspace = await readProjectFile("components/ProfileWorkspace.js");
  const editor = await readProjectFile("components/CustomFieldsEditor.js");

  assert.match(workspace, /goResolutionEnabled: false/);
  assert.match(
    workspace,
    /goResolutionEnabled=\{form\.goResolutionEnabled\}/,
  );
  assert.match(
    workspace,
    /onGoResolutionEnabledChange=\{\(goResolutionEnabled\) =>\s*updateForm\("goResolutionEnabled", goResolutionEnabled\)\s*\}/s,
  );
  assert.match(editor, /Resolve GO terms after aggregation/);
  assert.match(
    editor,
    /Runs after target and ortholog aggregation using the job's summary models; free-text categories are still extracted\./,
  );
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
