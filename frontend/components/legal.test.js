import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  CONTACT_PLACEHOLDER,
  LEGAL_DOCUMENTS,
  LEGAL_LINKS,
  RESEARCH_DISCLAIMER,
  TERMS_VERSION,
} from "../lib/legal.js";

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

async function readProjectFile(relativePath) {
  return readFile(path.join(projectRoot, relativePath), "utf8");
}

const LEGAL_PAGES = {
  terms: "app/legal/terms/page.js",
  privacy: "app/legal/privacy/page.js",
  "acceptable-use": "app/legal/acceptable-use/page.js",
  disclaimer: "app/legal/disclaimer/page.js",
};

test("TERMS_VERSION matches the backend default", () => {
  assert.equal(TERMS_VERSION, "draft-2026-09");
});

test("LEGAL_LINKS lists the four legal routes in footer order", () => {
  assert.deepEqual(LEGAL_LINKS, [
    { href: "/legal/terms", label: "Terms" },
    { href: "/legal/privacy", label: "Privacy" },
    { href: "/legal/acceptable-use", label: "Acceptable Use" },
    { href: "/legal/disclaimer", label: "Disclaimer" },
  ]);
});

test("each legal page renders LegalPlaceholder with its document", async () => {
  for (const [key, file] of Object.entries(LEGAL_PAGES)) {
    const page = await readProjectFile(file);
    assert.match(page, /import LegalPlaceholder from "[./]+components\/LegalPlaceholder"/, file);
    assert.match(page, /<LegalPlaceholder/, file);
    assert.match(page, new RegExp(`LEGAL_DOCUMENTS\\[["']${key}["']\\]`), file);
    assert.match(page, /<AppShell>/, file);
  }
});

test("legal documents carry a heading and non-empty checklist per section", () => {
  assert.deepEqual(Object.keys(LEGAL_DOCUMENTS).sort(), Object.keys(LEGAL_PAGES).sort());
  for (const [key, document] of Object.entries(LEGAL_DOCUMENTS)) {
    assert.ok(document.title, key);
    assert.ok(document.sections.length > 0, key);
    for (const section of document.sections) {
      assert.ok(section.heading, `${key}: missing heading`);
      assert.ok(section.mustInclude.length > 0, `${key}/${section.heading}`);
    }
  }
});

test("legal checklists cover the required topics", () => {
  const flat = (key) =>
    LEGAL_DOCUMENTS[key].sections
      .flatMap((section) => [section.heading, ...section.mustInclude])
      .join("\n");
  const terms = flat("terms");
  for (const topic of [
    /Operating entity/,
    /Eligibility/,
    /One person per account/,
    /"as is"/,
    /No uptime guarantee/,
    /Quotas and fair use/,
    /submitted data/,
    /Who owns generated annotations/,
    /Third-party literature rights/,
    /suspension/i,
    /Limitation of liability/,
    /Indemnification/,
    /Governing law/,
    /Changes to terms/,
    /Effective date/,
  ]) {
    assert.match(terms, topic);
  }
  const privacy = flat("privacy");
  for (const topic of [
    /IP addresses/,
    /Audit logs/,
    /Abuse prevention/,
    /GDPR/,
    /MongoDB Atlas/,
    /Resend/,
    /Cloudflare/,
    /HPC\/institution/,
    /Backups/,
    /ga_session/,
    /90-day sliding/,
    /deletion/,
    /Children/,
    /International transfers/,
  ]) {
    assert.match(privacy, topic);
  }
  const aup = flat("acceptable-use");
  for (const topic of [/scraping/, /account sharing/, /admin functions/, /DoS/, /sensitive personal data/, /Ban/, /abuse/]) {
    assert.match(aup, topic);
  }
  const disclaimer = flat("disclaimer");
  for (const topic of [/Research use only/, /diagnostic/, /outdated/, /available literature/, /No warranty/, /primary sources/, /decisions made from outputs/, /Citation/]) {
    assert.match(disclaimer, topic);
  }
});

test("legal copy uses placeholders instead of invented entities", () => {
  const all = JSON.stringify(LEGAL_DOCUMENTS);
  assert.match(all, /\[Operating entity\]/);
  assert.match(all, /\[contact email\]/);
});

test("disclaimer includes plain-language draft wording from the owner", () => {
  const draft = LEGAL_DOCUMENTS.disclaimer.draft.join(" ");
  assert.match(draft, /not responsible for inaccurate information/);
  assert.match(draft, /at your own risk/);
});

test("LegalPlaceholder shows the draft banner and per-section checklist", async () => {
  const component = await readProjectFile("components/LegalPlaceholder.js");
  assert.match(component, /export default function LegalPlaceholder\(\{ title, sections, draft \}\)/);
  assert.match(component, /DRAFT — pending legal review/);
  assert.match(component, /Must include/);
  assert.match(component, /section\.mustInclude\.map/);
  assert.match(component, /workbench-amber-bg/);
});

test("SiteFooter links the legal routes, data sources, and contact placeholder", async () => {
  const footer = await readProjectFile("components/SiteFooter.js");
  assert.match(footer, /LEGAL_LINKS\.map/);
  assert.match(footer, /NCBI/);
  assert.match(footer, /PubMed/);
  assert.match(footer, /PMC/);
  assert.match(footer, /Contact: \{CONTACT_PLACEHOLDER\}/);
});

test("contact placeholder stays an obvious placeholder", () => {
  assert.equal(CONTACT_PLACEHOLDER, "[contact email]");
});

test("AppShell renders the footer outside the session gate", async () => {
  const shell = await readProjectFile("components/AppShell.js");
  assert.match(shell, /import SiteFooter from "\.\/SiteFooter"/);
  assert.match(shell, /<\/div>\s*<SiteFooter \/>\s*<\/main>/);
});

test("signup form requires the terms checkbox and sends accept_terms", async () => {
  const forms = await readProjectFile("components/AuthForms.js");
  assert.match(forms, /type="checkbox"/);
  assert.match(forms, /I agree to the/);
  assert.match(forms, /href="\/legal\/terms"[^>]*target="_blank"/);
  assert.match(forms, /href="\/legal\/acceptable-use"[^>]*target="_blank"/);
  assert.match(forms, /rel="noopener noreferrer"/);
  assert.match(forms, /signup\(email\.trim\(\), username\.trim\(\) \|\| null, acceptTerms\)/);
  assert.match(forms, /disabled=\{submitting \|\| !acceptTerms\}/);
});

test("annotation detail shows the research disclaimer", async () => {
  assert.equal(
    RESEARCH_DISCLAIMER,
    "Research use only. AI-generated annotations can be incomplete or wrong. Verify against primary sources before relying on them.",
  );
  const explorer = await readProjectFile("components/AnnotationExplorer.js");
  assert.match(explorer, /import \{ RESEARCH_DISCLAIMER \} from "\.\.\/lib\/legal"/);
  assert.match(explorer, /\{RESEARCH_DISCLAIMER\}/);
  assert.match(explorer, /href="\/legal\/disclaimer"/);
});
