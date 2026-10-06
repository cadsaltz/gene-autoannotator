import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { isProtectedPath, isPublicPath } from "../../lib/authPaths.js";
import { GUIDE_SECTIONS } from "./guideSections.js";

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const guideDir = path.join(projectRoot, "components/guide");

async function readProjectFile(relativePath) {
  return readFile(path.join(projectRoot, relativePath), "utf8");
}

async function readGuideSources() {
  const names = (await readdir(guideDir)).filter(
    (name) => name.endsWith(".js") && !name.endsWith(".test.js"),
  );
  return Promise.all(
    names.map(async (name) => ({ name, source: await readFile(path.join(guideDir, name), "utf8") })),
  );
}

const SECTION_COMPONENTS = [
  ["HeroSection", "hero"],
  ["WhatYouGetSection", "what-you-get"],
  ["PipelineSection", "pipeline"],
  ["TutorialSection", "tutorial"],
  ["LimitsSection", "limits"],
  ["TradeoffsSection", "tradeoffs"],
  ["DisclaimerSection", "disclaimers"],
  ["CreditsSection", "credits"],
  ["FaqSection", "faq"],
];

test("homepage renders the nine guide sections in order inside a public AppShell", async () => {
  const page = await readProjectFile("app/page.js");
  assert.match(page, /<AppShell publicPage>/);
  let previous = -1;
  for (const [component] of SECTION_COMPONENTS) {
    assert.match(
      page,
      new RegExp(`import ${component} from "\\.\\./components/guide/${component}"`),
      component,
    );
    const index = page.indexOf(`<${component} />`);
    assert.ok(index > previous, `${component} renders after the previous section`);
    previous = index;
  }
  assert.match(page, /<GuideToc \/>/);
});

test("table of contents lists the nine section anchors in order", () => {
  assert.deepEqual(
    GUIDE_SECTIONS.map((section) => section.id),
    SECTION_COMPONENTS.map(([, id]) => id),
  );
  for (const section of GUIDE_SECTIONS) {
    assert.ok(section.label, section.id);
  }
});

test("each section file anchors itself to its table-of-contents id", async () => {
  for (const [component, id] of SECTION_COMPONENTS) {
    const source = await readProjectFile(`components/guide/${component}.js`);
    assert.match(source, new RegExp(`export default function ${component}\\(`), component);
    assert.match(source, new RegExp(`id="${id}"`), component);
  }
  const toc = await readProjectFile("components/guide/GuideToc.js");
  assert.match(toc, /aria-label="On this page"/);
  assert.match(toc, /GUIDE_SECTIONS\.map/);
  assert.match(toc, /href=\{`#\$\{section\.id\}`\}/);
});

test("hero is the only h1; other sections start at h2", async () => {
  for (const [component] of SECTION_COMPONENTS) {
    const source = await readProjectFile(`components/guide/${component}.js`);
    if (component === "HeroSection") {
      assert.match(source, /<h1[\s>]/);
    } else {
      assert.doesNotMatch(source, /<h1[\s>]/, component);
      assert.match(source, /<h2[\s>]/, component);
    }
  }
});

test("no guide file touches fleet or health endpoints", async () => {
  const sources = await readGuideSources();
  sources.push({ name: "app/page.js", source: await readProjectFile("app/page.js") });
  for (const { name, source } of sources) {
    assert.doesNotMatch(source, /getHealth|getWorkers|getAnnotationHealth/, name);
  }
});

test("only the signed-in-aware widgets are client components", async () => {
  const sources = await readGuideSources();
  const clientFiles = sources
    .filter(({ source }) => /^"use client";/m.test(source))
    .map(({ name }) => name)
    .sort();
  assert.deepEqual(clientFiles, ["HeroActions.js", "QueueLimits.js"]);
  const page = await readProjectFile("app/page.js");
  assert.doesNotMatch(page, /"use client"/);
});

test("hero actions switch between sign-up/sign-in and Go to Jobs", async () => {
  const actions = await readProjectFile("components/guide/HeroActions.js");
  assert.match(actions, /const \{ user \} = useSession\(\);/);
  assert.doesNotMatch(actions, /getMe|useEffect/);
  assert.match(actions, /href="\/signup"/);
  assert.match(actions, /href="\/login"/);
  assert.match(actions, /Go to Jobs/);
  assert.match(actions, /href="\/jobs"/);
  const hero = await readProjectFile("components/guide/HeroSection.js");
  assert.match(hero, /<HeroActions \/>/);
});

test("limits widget reads queue-status and falls back to generic copy", async () => {
  const limits = await readProjectFile("components/guide/QueueLimits.js");
  assert.match(limits, /import \{ getQueueStatus \} from "\.\.\/\.\.\/lib\/api"/);
  assert.match(limits, /your_active_limit/);
  assert.match(limits, /your_daily_limit/);
  assert.match(limits, /batch_limit/);
  assert.match(limits, /SIGNED_OUT_COPY/);
  assert.match(limits, /const \{ user \} = useSession\(\);/);
  assert.match(limits, /if \(!user\) return undefined;/);
  assert.match(limits, /: user \? \(\s*<p[^>]*>\{LOADING_COPY\}<\/p>/);
  assert.match(limits, /queueStatus\.paused === true/);
  assert.match(limits, /queue full/);
  const section = await readProjectFile("components/guide/LimitsSection.js");
  assert.match(section, /<QueueLimits \/>/);
  assert.match(section, /minutes to hours/);
  assert.match(section, /ten hours or more/);
});

test("copy stays precise about optional stages, flags, and passwords", async () => {
  const pipeline = await readProjectFile("components/guide/PipelineSection.js");
  assert.match(pipeline, /up to nine stages/);
  const tutorial = await readProjectFile("components/guide/TutorialSection.js");
  assert.match(tutorial, /such as strong_literature_support/);
  const faq = await readProjectFile("components/guide/FaqSection.js");
  assert.match(faq, /no password to leak/);
  const hero = await readProjectFile("components/guide/HeroSection.js");
  assert.doesNotMatch(hero, /<dt|<dd|<dl/);
});

test("example output card is a trimmed real annotation with a real PMID", async () => {
  const source = await readProjectFile("components/guide/WhatYouGetSection.js");
  assert.match(source, /const EXAMPLE_ANNOTATION = \{/);
  assert.match(source, /TcCLB\.503799\.4/);
  assert.match(source, /AUK1/);
  assert.match(source, /19320832/);
  assert.match(source, /https:\/\/pubmed\.ncbi\.nlm\.nih\.gov\//);
});

test("pipeline section lists the stages in pipeline order", async () => {
  const source = await readProjectFile("components/guide/PipelineSection.js");
  const stages = [
    "Gene resolution",
    "Literature retrieval",
    "Relevance filtering",
    "Section excerpting",
    "Multi-model summaries",
    "Consensus",
    "Aggregation",
    "GO term resolution",
    "Stored annotation",
  ];
  let previous = -1;
  for (const stage of stages) {
    const index = source.indexOf(`title: "${stage}`);
    assert.ok(index > previous, `${stage} appears after the previous stage`);
    previous = index;
  }
  assert.match(source, /<ol[\s>]/);
});

test("tutorial covers sign-up through reading citations", async () => {
  const source = await readProjectFile("components/guide/TutorialSection.js");
  for (const topic of [/6-digit code/, /My jobs/, /View annotation/, /No supported data/, /Quality flags/, /PMID/]) {
    assert.match(source, topic);
  }
});

test("tradeoffs cover errors, coverage, organisms, model modes, and completeness", async () => {
  const source = await readProjectFile("components/guide/TradeoffsSection.js");
  for (const topic of [/hallucinat/i, /PubMed Central/, /Custom organism/i, /performance/, /lite/, /complete/i]) {
    assert.match(source, topic);
  }
});

test("disclaimer section states the required points and links the Disclaimer page", async () => {
  const source = await readProjectFile("components/guide/DisclaimerSection.js");
  assert.match(source, /href="\/legal\/disclaimer"/);
  assert.match(source, /Research use only/);
  assert.match(source, /incomplete or wrong/);
  assert.match(source, /not responsible for inaccurate/);
  assert.match(source, /at your own risk/);
});

test("credits attribute NCBI sources and keep a citation placeholder", async () => {
  const source = await readProjectFile("components/guide/CreditsSection.js");
  for (const topic of [/NCBI/, /PubMed/, /PMC|PubMed Central/, /not endorsed by NCBI/, /\[Paper citation/]) {
    assert.match(source, topic);
  }
});

test("FAQ covers email codes, quotas, retention, and account deletion", async () => {
  const source = await readProjectFile("components/guide/FaqSection.js");
  assert.match(source, /href: "\/legal\/privacy"|href="\/legal\/privacy"/);
  assert.match(source, /CONTACT_PLACEHOLDER/);
  for (const topic of [/email code/i, /quotas/i, /kept/i, /delete/i, /HPC/]) {
    assert.match(source, topic);
  }
});

test("homepage stays public in middleware path rules", () => {
  assert.equal(isPublicPath("/"), true);
  assert.equal(isProtectedPath("/"), false);
});
