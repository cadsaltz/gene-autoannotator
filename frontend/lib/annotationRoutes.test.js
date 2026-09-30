import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

async function readProjectFile(relativePath) {
  return readFile(path.join(projectRoot, relativePath), "utf8");
}

const ANNOTATION_ROUTES = {
  search: "app/api/annotations/search/route.js",
  detail: "app/api/annotations/[annotationId]/route.js",
  versions: "app/api/annotations/[annotationId]/versions/route.js",
};

test("annotation health route is admin-only and never echoes error text", async () => {
  const route = await readProjectFile("app/api/annotations/health/route.js");
  assert.match(route, /requireAnnotationSession\(request, \{ admin: true \}\)/);
  assert.match(route, /if \(access\.response\) return access\.response;/);
  assert.doesNotMatch(route, /error\.message/);
});

test("Mongo health messages redact connection strings", async () => {
  const mongodb = await readProjectFile("lib/mongodb.js");
  assert.match(mongodb, /message: redactConnectionStrings\(error\.message\)/);
});

test("annotation data routes gate on the session and return generic 503s", async () => {
  for (const [name, file] of Object.entries(ANNOTATION_ROUTES)) {
    const route = await readProjectFile(file);
    assert.match(route, /const access = await requireAnnotationSession\(request\);/, name);
    assert.match(route, /if \(access\.response\) return access\.response;/, name);
    assert.doesNotMatch(route, /error\.message/, name);
    assert.match(route, /\{ detail: "Annotation storage is unavailable" \}, \{ status: 503 \}/, name);
  }
});

test("annotation detail and versions routes only include job details for admins", async () => {
  for (const name of ["detail", "versions"]) {
    const route = await readProjectFile(ANNOTATION_ROUTES[name]);
    assert.match(route, /includeJobDetails: access\.user\.role === "admin"/, name);
  }
});

test("annotations page checks the session before searching", async () => {
  const page = await readProjectFile("app/annotations/page.js");
  assert.match(page, /const session = await getServerSession\(\);/);
  assert.match(page, /loadAnnotationsPage\(\{/);
  assert.match(page, /if \(initial\.redirectTo\) \{\s*redirect\(initial\.redirectTo\);\s*\}/);
  assert.doesNotMatch(page, /error\.message/);
});

test("AnnotationExplorer hides job ids when the API omits them", async () => {
  const explorer = await readProjectFile("components/AnnotationExplorer.js");
  assert.match(explorer, /\{displayAnnotation\.job_id \? \(/);
  assert.match(explorer, /\{option\.job_id \? ` · job \$\{option\.job_id\}` : ""\}/);
  assert.doesNotMatch(explorer, /job_id \|\| "Unknown"/);
});

test("auth pages render AppShell as public pages", async () => {
  for (const file of ["app/login/page.js", "app/signup/page.js", "app/auth/verify/page.js"]) {
    const page = await readProjectFile(file);
    assert.match(page, /<AppShell publicPage>/, file);
  }
});

test("not-found page is public, friendly, and links home", async () => {
  await access(path.join(projectRoot, "app/not-found.js"));
  const page = await readProjectFile("app/not-found.js");
  assert.match(page, /<AppShell publicPage>/);
  assert.match(page, /<Link href="\/"/);
  assert.match(page, /Page not found/);
});
