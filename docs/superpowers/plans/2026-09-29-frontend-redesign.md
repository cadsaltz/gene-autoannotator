# Frontend Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-skin the Next.js frontend on Untitled UI foundations with light/dark/system themes, and rebuild the annotations page as a full-width two-pane layout.

**Architecture:** Semantic colour tokens (CSS variables) are defined once for light and once under `[data-theme="dark"]` in `app/globals.css` and exposed to Tailwind via `@theme inline`; components only use token utilities, so dark mode is a token swap. A tiny inline script sets `data-theme` before paint; a header switch persists the choice in `localStorage`. The annotations page is split from one 586-line component into focused components under `components/annotations/`, driven by small pure helpers in `lib/` that carry the unit tests.

**Tech Stack:** Next.js 16 App Router (plain JS, React 19), Tailwind CSS v4, `next/font/google`, `node --test` source and unit tests, ESLint (`eslint-config-next`).

**Spec:** `docs/superpowers/specs/2026-09-29-frontend-redesign-design.md`.
**Visual reference:** `docs/superpowers/specs/2026-09-29-frontend-redesign/annotations-redesign.html` (open in a browser; `?theme=dark` shows dark mode).

## Global Constraints

- Cosmetic only: no API, data shape, auth, role, route, or search-behaviour changes.
- One design reference: Untitled UI foundations (Inter, Roboto Mono, gray scales, 6/8/12px radii, xs/sm shadows), teal brand. No other design systems, no new npm dependencies.
- Components must not contain hard-coded colours: no `[#hex]` Tailwind values, no `slate-*`/`gray-*`/`zinc-*`/`stone-*`/`neutral-*`/`black` palette utilities, no `bg-white*`. Use token utilities (`bg-surface`, `text-fg-secondary`, `border-line`, …). `text-white` is allowed only on `bg-brand` (and the white spinner on primary buttons).
- Typography: no `font-bold`/`font-extrabold`/`font-black` (use `font-semibold` max), no arbitrary `tracking-[…]` (use `tracking-tight` for large headings), no uppercase micro-labels. Radii: no `rounded-2xl`, `rounded-3xl`, `rounded-[…px]` (cards are `rounded-xl`).
- Theme: choices `light` | `dark` | `system`, default `system`, stored in `localStorage["ga-theme"]`.
- GO terms never show confidence, agreement, or votes.
- All frontend commands run from `frontend/`. `npm` is a snap: shell commands that run `npm` or `node` need to run outside the sandbox; `npm run build` also needs network for Google Fonts.
- Do not touch these pre-existing uncommitted files (they are the user's work): `autoannotation/http_.py`, `autoannotation/worker_env.py`, `experiments/paper/tests/test_paper_experiment_bias_runner.py`, `shared/env_persist.py`, `worker.env.example`, `worker/README.md`, `worker/bootstrap.py`, `worker/fleet/setup.py`. Stage files explicitly by path; never `git add -A` or `git add .`.
- Baseline: `npm test` passes 301 tests on `master` before this work.

## File Structure

| File | Responsibility |
|---|---|
| `frontend/app/globals.css` | Tokens (light + dark), Tailwind theme mapping, restyled `workbench-*`/`guide-*` vocabulary |
| `frontend/app/layout.js` | Inter + Roboto Mono fonts, no-flash theme script |
| `frontend/lib/theme.js` | Theme constants, choice normalisation, resolution, init script |
| `frontend/components/icons.js` | Shared stroke icons and the logo mark |
| `frontend/components/ThemeToggle.js` | Light / dark / system segmented switch |
| `frontend/components/AppShell.js` | Header, content width (`fullWidth`), session gating |
| `frontend/components/SiteFooter.js` | Footer (token restyle) |
| `frontend/components/designTokens.test.js` | Guard tests for colours, typography, radii |
| `frontend/lib/citations.js` | PMID citation parsing and NCBI URLs |
| `frontend/lib/annotationLayout.js` | Compact vs prose field classification, grid plan |
| `frontend/lib/annotationSummary.js` | Stat strip cells, coverage, name source, papers, notes, flags, organism filter |
| `frontend/components/annotations/ui.js` | Badge, Card, CardHeader, Meter primitives |
| `frontend/components/annotations/CitedText.js` | Text with PMID chips |
| `frontend/components/annotations/PapersTable.js` | Selected-papers table |
| `frontend/components/annotations/OverviewTab.js` | Annotation tab grid |
| `frontend/components/annotations/ResultsRail.js` | Search, filter, result list |
| `frontend/components/annotations/AnnotationHeader.js` | Breadcrumbs, title, badges, actions, notices |
| `frontend/components/annotations/StatStrip.js` | Six stat cells |
| `frontend/components/annotations/AnnotationTabs.js` | Accessible tablist |
| `frontend/components/annotations/LiteratureTab.js` | Papers table + PMC IDs |
| `frontend/components/annotations/VersionsTab.js` | Version history list |
| `frontend/components/annotations/OrthologTab.js` | Target vs ortholog comparison |
| `frontend/components/annotations/MetadataTab.js` | Metadata description list |
| `frontend/components/annotations/AnnotationDetail.js` | Composes header, stats, tabs, panels |
| `frontend/components/AnnotationExplorer.js` | State + two-pane layout |

---

### Task 1: Theme foundation (tokens, fonts, theme helper, no-flash script)

**Files:**
- Create: `frontend/lib/theme.js`
- Create: `frontend/lib/theme.test.js`
- Modify: `frontend/app/globals.css` (full rewrite)
- Modify: `frontend/app/layout.js` (full rewrite)

**Interfaces:**
- Produces: `THEME_STORAGE_KEY = "ga-theme"`, `THEME_CHANGE_EVENT = "ga-theme-change"`, `THEME_CHOICES = ["light","dark","system"]`, `DARK_MEDIA_QUERY = "(prefers-color-scheme: dark)"`, `normalizeThemeChoice(value) -> "light"|"dark"|"system"`, `resolveTheme(choice, prefersDark: boolean) -> "light"|"dark"`, `THEME_INIT_SCRIPT: string`.
- Produces Tailwind token utilities used by every later task: colours `page`, `surface`, `surface-muted`, `surface-sunken`, `line`, `line-strong`, `fg`, `fg-secondary`, `fg-tertiary`, `fg-muted`, `fg-subtle`, `brand`, `brand-hover`, `brand-fg`, `brand-tint`, `brand-tint-strong`, `brand-line`, `warning-{fg,solid,tint,line}`, `success-{fg,solid,tint,line}`, `error-{fg,solid,tint,line}`, `info-{fg,tint,line}`, `focus-ring`; shadows `shadow-xs`, `shadow-sm`; fonts `font-sans`, `font-mono`.

- [ ] **Step 1: Write the failing tests** — create `frontend/lib/theme.test.js`:

```js
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

import {
  DARK_MEDIA_QUERY,
  THEME_CHOICES,
  THEME_INIT_SCRIPT,
  THEME_STORAGE_KEY,
  normalizeThemeChoice,
  resolveTheme,
} from "./theme.js";

const projectRoot = process.cwd();

function runInitScript({ stored, prefersDark = false, throws = false }) {
  const root = { dataset: {} };
  const localStorage = {
    getItem(key) {
      if (throws) throw new Error("blocked");
      return key === THEME_STORAGE_KEY ? stored : null;
    },
  };
  const window = {
    matchMedia(query) {
      assert.equal(query, DARK_MEDIA_QUERY);
      return { matches: prefersDark };
    },
  };
  new Function("localStorage", "window", "document", THEME_INIT_SCRIPT)(localStorage, window, {
    documentElement: root,
  });
  return root.dataset.theme;
}

test("theme choices are light, dark, and system", () => {
  assert.deepEqual(THEME_CHOICES, ["light", "dark", "system"]);
  assert.equal(THEME_STORAGE_KEY, "ga-theme");
});

test("normalizeThemeChoice falls back to system for unknown values", () => {
  assert.equal(normalizeThemeChoice("dark"), "dark");
  assert.equal(normalizeThemeChoice("light"), "light");
  assert.equal(normalizeThemeChoice("system"), "system");
  assert.equal(normalizeThemeChoice("purple"), "system");
  assert.equal(normalizeThemeChoice(null), "system");
});

test("resolveTheme follows the OS only in system mode", () => {
  assert.equal(resolveTheme("light", true), "light");
  assert.equal(resolveTheme("dark", false), "dark");
  assert.equal(resolveTheme("system", true), "dark");
  assert.equal(resolveTheme("system", false), "light");
  assert.equal(resolveTheme("bogus", true), "dark");
});

test("init script applies the stored choice before paint", () => {
  assert.equal(runInitScript({ stored: "dark" }), "dark");
  assert.equal(runInitScript({ stored: "light", prefersDark: true }), "light");
  assert.equal(runInitScript({ stored: null, prefersDark: true }), "dark");
  assert.equal(runInitScript({ stored: "nonsense", prefersDark: false }), "light");
});

test("init script never throws when storage is blocked", () => {
  assert.equal(runInitScript({ stored: "dark", throws: true }), undefined);
});

test("every light token has a dark-theme value", async () => {
  const css = await readFile(path.join(projectRoot, "app/globals.css"), "utf8");
  const block = (selector) => {
    const start = css.indexOf(`${selector} {`);
    assert.notEqual(start, -1, `missing ${selector} block`);
    return css.slice(start, css.indexOf("}", start));
  };
  const names = (text) => [...text.matchAll(/(--[a-z0-9-]+)\s*:/g)].map((match) => match[1]).sort();
  const light = names(block(":root"));
  assert.ok(light.includes("--surface") && light.includes("--brand"), "core tokens defined");
  assert.deepEqual(names(block('[data-theme="dark"]')), light);
});

test("root layout loads Inter and injects the theme script", async () => {
  const layout = await readFile(path.join(projectRoot, "app/layout.js"), "utf8");
  assert.match(layout, /Inter\(/);
  assert.match(layout, /Roboto_Mono\(/);
  assert.match(layout, /suppressHydrationWarning/);
  assert.match(layout, /dangerouslySetInnerHTML=\{\{ __html: THEME_INIT_SCRIPT \}\}/);
  assert.doesNotMatch(layout, /Geist/);
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && node --test lib/theme.test.js`
Expected: FAIL — `Cannot find module '.../lib/theme.js'`.

- [ ] **Step 3: Create `frontend/lib/theme.js`**

```js
export const THEME_STORAGE_KEY = "ga-theme";
export const THEME_CHANGE_EVENT = "ga-theme-change";
export const THEME_CHOICES = ["light", "dark", "system"];
export const DARK_MEDIA_QUERY = "(prefers-color-scheme: dark)";

export function normalizeThemeChoice(value) {
  return THEME_CHOICES.includes(value) ? value : "system";
}

export function resolveTheme(choice, prefersDark) {
  const normalized = normalizeThemeChoice(choice);
  if (normalized === "system") {
    return prefersDark ? "dark" : "light";
  }
  return normalized;
}

// Inlined into <head> so the stored theme is applied before first paint.
export const THEME_INIT_SCRIPT = `(function(){try{var c=localStorage.getItem(${JSON.stringify(
  THEME_STORAGE_KEY,
)});if(c!=="light"&&c!=="dark")c="system";var d=c==="dark"||(c==="system"&&window.matchMedia(${JSON.stringify(
  DARK_MEDIA_QUERY,
)}).matches);document.documentElement.dataset.theme=d?"dark":"light";}catch(e){}})();`;
```

- [ ] **Step 4: Rewrite `frontend/app/globals.css`**

```css
@import "tailwindcss";

/* Foundations follow Untitled UI (MIT): Inter, its gray scales, 6/8/12px radii and
   xs/sm shadows, with a teal brand. Components reference only these semantic tokens,
   so the dark theme is a token swap with no per-component rules. Every token in
   :root must also be defined in the dark block. */
:root {
  color-scheme: light;
  --page: #f9fafb;
  --surface: #ffffff;
  --surface-muted: #f9fafb;
  --surface-sunken: #f2f4f7;
  --line: #eaecf0;
  --line-strong: #d0d5dd;
  --fg: #101828;
  --fg-secondary: #344054;
  --fg-tertiary: #475467;
  --fg-muted: #667085;
  --fg-subtle: #98a2b3;
  --brand: #0f766e;
  --brand-hover: #115e59;
  --brand-fg: #0f766e;
  --brand-tint: #f0fdfa;
  --brand-tint-strong: #ccfbf1;
  --brand-line: #99f6e4;
  --warning-fg: #b54708;
  --warning-solid: #dc6803;
  --warning-tint: #fffaeb;
  --warning-line: #fedf89;
  --success-fg: #067647;
  --success-solid: #17b26a;
  --success-tint: #ecfdf3;
  --success-line: #abefc6;
  --error-fg: #b42318;
  --error-solid: #d92d20;
  --error-tint: #fef3f2;
  --error-line: #fecdca;
  --info-fg: #175cd3;
  --info-tint: #eff8ff;
  --info-line: #b2ddff;
  --focus-ring: rgb(15 118 110 / 24%);
  --elev-xs: 0 1px 2px rgb(16 24 40 / 5%);
  --elev-sm: 0 1px 3px rgb(16 24 40 / 10%), 0 1px 2px -1px rgb(16 24 40 / 10%);
}

[data-theme="dark"] {
  color-scheme: dark;
  --page: #0c111d;
  --surface: #161b26;
  --surface-muted: #0c111d;
  --surface-sunken: #1f242f;
  --line: #333741;
  --line-strong: #333741;
  --fg: #f5f5f6;
  --fg-secondary: #cecfd2;
  --fg-tertiary: #cecfd2;
  --fg-muted: #94969c;
  --fg-subtle: #85888e;
  --brand: #0f766e;
  --brand-hover: #0d9488;
  --brand-fg: #5eead4;
  --brand-tint: rgb(45 212 191 / 10%);
  --brand-tint-strong: rgb(45 212 191 / 22%);
  --brand-line: rgb(45 212 191 / 32%);
  --warning-fg: #fec84b;
  --warning-solid: #fdb022;
  --warning-tint: rgb(247 144 9 / 10%);
  --warning-line: rgb(247 144 9 / 32%);
  --success-fg: #75e0a7;
  --success-solid: #47cd89;
  --success-tint: rgb(23 178 106 / 10%);
  --success-line: rgb(23 178 106 / 32%);
  --error-fg: #fda29b;
  --error-solid: #f97066;
  --error-tint: rgb(240 68 56 / 10%);
  --error-line: rgb(240 68 56 / 32%);
  --info-fg: #84caff;
  --info-tint: rgb(46 144 250 / 10%);
  --info-line: rgb(46 144 250 / 32%);
  --focus-ring: rgb(45 212 191 / 30%);
  --elev-xs: 0 1px 2px rgb(0 0 0 / 40%);
  --elev-sm: 0 1px 3px rgb(0 0 0 / 50%), 0 1px 2px -1px rgb(0 0 0 / 50%);
}

@theme inline {
  --color-page: var(--page);
  --color-surface: var(--surface);
  --color-surface-muted: var(--surface-muted);
  --color-surface-sunken: var(--surface-sunken);
  --color-line: var(--line);
  --color-line-strong: var(--line-strong);
  --color-fg: var(--fg);
  --color-fg-secondary: var(--fg-secondary);
  --color-fg-tertiary: var(--fg-tertiary);
  --color-fg-muted: var(--fg-muted);
  --color-fg-subtle: var(--fg-subtle);
  --color-brand: var(--brand);
  --color-brand-hover: var(--brand-hover);
  --color-brand-fg: var(--brand-fg);
  --color-brand-tint: var(--brand-tint);
  --color-brand-tint-strong: var(--brand-tint-strong);
  --color-brand-line: var(--brand-line);
  --color-warning-fg: var(--warning-fg);
  --color-warning-solid: var(--warning-solid);
  --color-warning-tint: var(--warning-tint);
  --color-warning-line: var(--warning-line);
  --color-success-fg: var(--success-fg);
  --color-success-solid: var(--success-solid);
  --color-success-tint: var(--success-tint);
  --color-success-line: var(--success-line);
  --color-error-fg: var(--error-fg);
  --color-error-solid: var(--error-solid);
  --color-error-tint: var(--error-tint);
  --color-error-line: var(--error-line);
  --color-info-fg: var(--info-fg);
  --color-info-tint: var(--info-tint);
  --color-info-line: var(--info-line);
  --color-focus-ring: var(--focus-ring);
  --shadow-xs: var(--elev-xs);
  --shadow-sm: var(--elev-sm);
  --font-sans: var(--font-inter), ui-sans-serif, system-ui, sans-serif;
  --font-mono: var(--font-roboto-mono), ui-monospace, SFMono-Regular, Menlo, monospace;
}

body {
  background: var(--page);
  color: var(--fg);
  font-family: var(--font-inter), ui-sans-serif, system-ui, sans-serif;
}

button,
input,
select,
textarea {
  font: inherit;
}

:where(a, button, select, summary):focus-visible {
  outline: 2px solid var(--brand-fg);
  outline-offset: 2px;
}

@media (prefers-reduced-motion: no-preference) {
  html {
    scroll-behavior: smooth;
  }
}

.workbench-app {
  min-height: 100vh;
  background: var(--page);
  color: var(--fg);
}

.workbench-card {
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--surface);
  box-shadow: var(--elev-xs);
}

.workbench-surface {
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--surface);
}

.workbench-surface-bg {
  background: var(--surface);
}

.workbench-muted-bg {
  background: var(--surface-muted);
}

.workbench-amber-bg {
  background: var(--warning-tint);
}

.workbench-foreground {
  color: var(--fg);
}

.workbench-muted {
  color: var(--fg-muted);
}

.workbench-green {
  color: var(--brand-fg);
}

.workbench-amber {
  color: var(--warning-fg);
}

.workbench-red {
  color: var(--error-fg);
}

.workbench-border {
  border-color: var(--line);
}

.workbench-border-green {
  border-color: var(--brand-line);
}

.workbench-border-amber {
  border-color: var(--warning-line);
}

.workbench-border-blue {
  border-color: var(--info-line);
}

.workbench-border-red {
  border-color: var(--error-line);
}

.health-status-ok {
  border-top: 4px solid var(--success-solid);
}

.health-status-warn {
  border-top: 4px solid var(--warning-solid);
}

.workbench-kicker {
  color: var(--brand-fg);
  font-size: 0.875rem;
  font-weight: 600;
}

.workbench-button {
  display: inline-flex;
  min-height: 2.5rem;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  border-radius: 8px;
  padding: 0 0.875rem;
  font-size: 0.875rem;
  font-weight: 600;
  white-space: nowrap;
  box-shadow: var(--elev-xs);
  transition:
    border-color 150ms ease,
    background-color 150ms ease,
    color 150ms ease,
    opacity 150ms ease;
}

.workbench-button-primary {
  border: 1px solid var(--brand);
  background: var(--brand);
  color: #fff;
}

.workbench-button-primary:hover {
  border-color: var(--brand-hover);
  background: var(--brand-hover);
}

.workbench-button-secondary {
  border: 1px solid var(--line-strong);
  background: var(--surface);
  color: var(--fg-secondary);
}

.workbench-button-secondary:hover {
  background: var(--surface-muted);
  color: var(--fg);
}

.workbench-input {
  min-height: 2.5rem;
  border: 1px solid var(--line-strong);
  border-radius: 8px;
  background: var(--surface);
  padding: 0.5rem 0.75rem;
  color: var(--fg);
  box-shadow: var(--elev-xs);
  outline: none;
}

.workbench-input::placeholder {
  color: var(--fg-subtle);
}

.workbench-input:focus {
  border-color: var(--brand-line);
  box-shadow: 0 0 0 4px var(--focus-ring);
}

.annotation-raw-json {
  display: block;
  width: 100%;
  max-width: 100%;
  min-width: 0;
  overflow: auto;
  white-space: pre;
}

.job-card-running {
  border-left-color: var(--brand-fg);
  background: linear-gradient(90deg, var(--brand-tint), var(--surface) 42%);
}

.job-card-completed {
  border-left-color: var(--success-solid);
  background: var(--surface);
}

.job-card-failed {
  border-left-color: var(--error-solid);
  background: var(--error-tint);
}

.job-card-queued {
  border-left-color: var(--line-strong);
  background: var(--surface);
}

.job-card-cancelled {
  border-left-color: var(--line);
  background: var(--surface-muted);
}

.guide-hero {
  border: 1px solid var(--line);
  border-radius: 12px;
  background:
    radial-gradient(circle at 88% 12%, var(--brand-tint-strong), transparent 46%),
    var(--surface);
  color: var(--fg);
  box-shadow: var(--elev-xs);
}

.guide-kicker-amber {
  color: var(--warning-fg);
}

.guide-hero-muted {
  color: var(--fg-tertiary);
}

.guide-hero-stat {
  border-top: 1px solid var(--line);
}

.guide-button-light {
  background: var(--brand);
  color: #fff;
}

.guide-button-light:hover {
  background: var(--brand-hover);
}

.guide-button-outline {
  border: 1px solid var(--line-strong);
  background: var(--surface);
  color: var(--fg-secondary);
}

.guide-button-outline:hover {
  background: var(--surface-muted);
  color: var(--fg);
}

.guide-toc-link {
  border: 1px solid var(--line);
  color: var(--fg-secondary);
  transition:
    border-color 150ms ease,
    background-color 150ms ease;
}

@media (min-width: 64rem) {
  .guide-toc-link {
    border-color: transparent;
  }
}

.guide-toc-link:hover {
  border-color: var(--brand-line);
  background: var(--brand-tint);
}

.guide-step-badge {
  display: inline-flex;
  width: 2rem;
  height: 2rem;
  flex: none;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  background: var(--brand-tint-strong);
  color: var(--brand-fg);
  font-family: var(--font-roboto-mono), monospace;
  font-size: 0.75rem;
  font-weight: 600;
}

.guide-chip {
  display: inline-flex;
  align-items: center;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--surface-muted);
  padding: 0.125rem 0.625rem;
  font-size: 0.75rem;
  font-weight: 500;
  color: var(--fg-secondary);
}

.guide-chip-green {
  border-color: var(--success-line);
  background: var(--success-tint);
  color: var(--success-fg);
}

.guide-chip-amber {
  border-color: var(--warning-line);
  background: var(--warning-tint);
  color: var(--warning-fg);
}

.guide-faq summary {
  list-style: none;
}

.guide-faq summary::-webkit-details-marker {
  display: none;
}

.guide-faq summary::after {
  content: "+";
  margin-left: auto;
  color: var(--brand-fg);
  font-weight: 600;
}

.guide-faq[open] summary::after {
  content: "–";
}
```

The old `workbench-nav*` classes are intentionally gone; `AppShell` still references them until Task 2, so the header looks unstyled in between. That is expected.

- [ ] **Step 5: Rewrite `frontend/app/layout.js`**

```js
import { Inter, Roboto_Mono } from "next/font/google";

import { THEME_INIT_SCRIPT } from "../lib/theme";
import "./globals.css";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
});

const robotoMono = Roboto_Mono({
  variable: "--font-roboto-mono",
  subsets: ["latin"],
});

export const metadata = {
  title: "Gene Autoannotator",
  description: "Web UI for queued gene annotation jobs and generated annotation history",
};

export default function RootLayout({ children }) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${robotoMono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
```

- [ ] **Step 6: Run the tests**

Run: `cd frontend && node --test lib/theme.test.js && npm test 2>&1 | grep -E '^# (tests|pass|fail)'`
Expected: theme tests PASS; full suite `# fail 0`.

- [ ] **Step 7: Commit**

```bash
git add frontend/lib/theme.js frontend/lib/theme.test.js frontend/app/globals.css frontend/app/layout.js
git commit -m "feat(frontend): Untitled UI tokens with dark theme, Inter fonts, no-flash theme script"
```

---

### Task 2: Header, theme switch, footer, full-width shell

**Files:**
- Create: `frontend/components/icons.js`
- Create: `frontend/components/ThemeToggle.js`
- Modify: `frontend/components/AppShell.js` (full rewrite)
- Modify: `frontend/components/SiteFooter.js` (class changes only)
- Modify: `frontend/components/legal.test.js:153` (signature regex)
- Modify: `frontend/components/AppShell.test.js` (append tests)

**Interfaces:**
- Consumes (Task 1): `THEME_STORAGE_KEY`, `THEME_CHANGE_EVENT`, `DARK_MEDIA_QUERY`, `normalizeThemeChoice`, `resolveTheme`; token utilities.
- Produces: `AppShell({ children, publicPage = false, fullWidth = false })`; icons `SunIcon`, `MoonIcon`, `MonitorIcon`, `PlusIcon`, `SearchIcon`, `ChevronDownIcon`, `RefreshIcon`, `AlertIcon`, `CloseIcon`, `CheckIcon`, `MinusIcon`, `LogoMark` — every icon takes `{ size = 16, strokeWidth = 2, className = "" }` and renders `aria-hidden` SVG.

- [ ] **Step 1: Write the failing tests** — append to `frontend/components/AppShell.test.js`:

```js
test("AppShell supports a full-width content area", async () => {
  const shell = await readProjectFile("components/AppShell.js");
  assert.match(shell, /export default function AppShell\(\{ children, publicPage = false, fullWidth = false \}\)/);
  assert.match(shell, /fullWidth \? "w-full flex-1" : "mx-auto w-full max-w-7xl flex-1 px-6 py-8"/);
});

test("AppShell header has the theme switch on every page", async () => {
  const shell = await readProjectFile("components/AppShell.js");
  assert.match(shell, /import ThemeToggle from "\.\/ThemeToggle"/);
  assert.match(shell, /<ThemeToggle \/>/);
  assert.doesNotMatch(shell, /workbench-nav/);
});

test("ThemeToggle offers light, dark, and system and persists the choice", async () => {
  const toggle = await readProjectFile("components/ThemeToggle.js");
  assert.match(toggle, /"use client"/);
  assert.match(toggle, /role="group"/);
  assert.match(toggle, /aria-pressed=\{choice === option\.value\}/);
  assert.match(toggle, /localStorage\.setItem\(THEME_STORAGE_KEY, next\)/);
  assert.match(toggle, /useSyncExternalStore\(subscribe, readChoice, \(\) => "system"\)/);
  for (const value of ["light", "dark", "system"]) {
    assert.match(toggle, new RegExp(`value: "${value}"`));
  }
});
```

And in `frontend/components/legal.test.js` replace the line

```js
  assert.match(shell, /export default function AppShell\(\{ children, publicPage = false \}\)/);
```

with

```js
  assert.match(shell, /export default function AppShell\(\{ children, publicPage = false(, fullWidth = false)? \}\)/);
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && node --test components/AppShell.test.js`
Expected: FAIL on the three new tests (no `fullWidth`, no `ThemeToggle`, missing file).

- [ ] **Step 3: Create `frontend/components/icons.js`**

```jsx
function Icon({ size = 16, strokeWidth = 2, className = "", children }) {
  return (
    <svg
      aria-hidden="true"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`shrink-0 ${className}`}
    >
      {children}
    </svg>
  );
}

export function SunIcon(props) {
  return (
    <Icon {...props}>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </Icon>
  );
}

export function MoonIcon(props) {
  return (
    <Icon {...props}>
      <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" />
    </Icon>
  );
}

export function MonitorIcon(props) {
  return (
    <Icon {...props}>
      <rect x="3" y="4" width="18" height="12" rx="2" />
      <path d="M8 20h8M12 16v4" />
    </Icon>
  );
}

export function PlusIcon(props) {
  return (
    <Icon {...props}>
      <path d="M12 5v14M5 12h14" />
    </Icon>
  );
}

export function SearchIcon(props) {
  return (
    <Icon {...props}>
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" />
    </Icon>
  );
}

export function ChevronDownIcon(props) {
  return (
    <Icon {...props}>
      <path d="m6 9 6 6 6-6" />
    </Icon>
  );
}

export function RefreshIcon(props) {
  return (
    <Icon {...props}>
      <path d="M21 12a9 9 0 1 1-3-6.7L21 8" />
      <path d="M21 3v5h-5" />
    </Icon>
  );
}

export function AlertIcon(props) {
  return (
    <Icon {...props}>
      <path d="M12 9v4M12 17h.01" />
      <path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" />
    </Icon>
  );
}

export function CloseIcon(props) {
  return (
    <Icon {...props}>
      <path d="M18 6 6 18M6 6l12 12" />
    </Icon>
  );
}

export function CheckIcon(props) {
  return (
    <Icon strokeWidth={2.5} {...props}>
      <path d="M20 6 9 17l-5-5" />
    </Icon>
  );
}

export function MinusIcon(props) {
  return (
    <Icon {...props}>
      <path d="M5 12h14" />
    </Icon>
  );
}

export function LogoMark() {
  return (
    <span className="grid size-8 place-items-center rounded-lg bg-brand text-white shadow-xs">
      <Icon size={18} strokeWidth={2.2}>
        <path d="M7 3c0 6 10 6 10 12s-10 6-10 6M17 3c0 6-10 6-10 12" />
      </Icon>
    </span>
  );
}
```

- [ ] **Step 4: Create `frontend/components/ThemeToggle.js`**

```jsx
"use client";

import { useEffect, useSyncExternalStore } from "react";

import {
  DARK_MEDIA_QUERY,
  THEME_CHANGE_EVENT,
  THEME_STORAGE_KEY,
  normalizeThemeChoice,
  resolveTheme,
} from "../lib/theme";
import { MonitorIcon, MoonIcon, SunIcon } from "./icons";

const OPTIONS = [
  { value: "light", label: "Light theme", Icon: SunIcon },
  { value: "dark", label: "Dark theme", Icon: MoonIcon },
  { value: "system", label: "Match system theme", Icon: MonitorIcon },
];

function subscribe(onChange) {
  window.addEventListener("storage", onChange);
  window.addEventListener(THEME_CHANGE_EVENT, onChange);
  return () => {
    window.removeEventListener("storage", onChange);
    window.removeEventListener(THEME_CHANGE_EVENT, onChange);
  };
}

function readChoice() {
  try {
    return normalizeThemeChoice(window.localStorage.getItem(THEME_STORAGE_KEY));
  } catch {
    return "system";
  }
}

function applyChoice(choice) {
  const prefersDark = window.matchMedia(DARK_MEDIA_QUERY).matches;
  document.documentElement.dataset.theme = resolveTheme(choice, prefersDark);
}

export default function ThemeToggle() {
  const choice = useSyncExternalStore(subscribe, readChoice, () => "system");

  useEffect(() => {
    function onStorage(event) {
      if (event.key === THEME_STORAGE_KEY) {
        applyChoice(readChoice());
      }
    }
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  useEffect(() => {
    if (choice !== "system") {
      return undefined;
    }
    const media = window.matchMedia(DARK_MEDIA_QUERY);
    const onMediaChange = () => applyChoice("system");
    media.addEventListener("change", onMediaChange);
    return () => media.removeEventListener("change", onMediaChange);
  }, [choice]);

  function select(next) {
    window.localStorage.setItem(THEME_STORAGE_KEY, next);
    applyChoice(next);
    window.dispatchEvent(new Event(THEME_CHANGE_EVENT));
  }

  return (
    <div
      role="group"
      aria-label="Color theme"
      className="inline-flex gap-0.5 rounded-lg border border-line bg-surface-muted p-0.5"
    >
      {OPTIONS.map((option) => (
        <button
          key={option.value}
          type="button"
          title={option.label}
          aria-label={option.label}
          aria-pressed={choice === option.value}
          onClick={() => select(option.value)}
          className={`grid size-8 place-items-center rounded-md transition ${
            choice === option.value
              ? "bg-surface text-fg shadow-xs"
              : "text-fg-muted hover:text-fg-secondary"
          }`}
        >
          <option.Icon />
        </button>
      ))}
    </div>
  );
}
```

- [ ] **Step 5: Rewrite `frontend/components/AppShell.js`**

```jsx
"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { getMe, logout } from "../lib/authApi";
import { isNavItemActive, navItemsFor } from "../lib/navItems";
import { LogoMark, PlusIcon } from "./icons";
import SiteFooter from "./SiteFooter";
import ThemeToggle from "./ThemeToggle";

function SuspendedCard() {
  return (
    <section className="mx-auto max-w-md">
      <div className="workbench-card p-7">
        <p className="workbench-kicker">Account</p>
        <h1 className="workbench-foreground mt-2 text-3xl font-semibold tracking-tight">
          This account is suspended
        </h1>
        <p className="mt-4 text-sm workbench-muted">
          Contact the site administrators if you think this is a mistake.
        </p>
      </div>
    </section>
  );
}

function SessionLoading() {
  return (
    <p className="p-6 text-sm workbench-muted" role="status">
      Loading…
    </p>
  );
}

function initialsFor(user) {
  const source = String(user?.username || user?.email || "?").trim();
  return source.slice(0, 2).toUpperCase();
}

export default function AppShell({ children, publicPage = false, fullWidth = false }) {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState(null);
  const [suspended, setSuspended] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    getMe()
      .then((me) => {
        if (!cancelled) {
          setUser(me);
          setSuspended(false);
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setUser(null);
          setSuspended(error?.status === 403);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const signedIn = Boolean(user);
  const visibleNavItems = suspended ? navItemsFor(null).slice(0, 1) : navItemsFor(user);

  async function handleSignOut() {
    try {
      await logout();
    } catch {
      // Clear local state even if logout request fails.
    }
    setUser(null);
    setSuspended(false);
    router.push("/login");
    router.refresh();
  }

  return (
    <main className="workbench-app flex flex-col">
      <header className="sticky top-0 z-30 border-b border-line bg-surface">
        <div className="flex min-h-16 flex-wrap items-center gap-x-8 gap-y-2 px-4 py-3 sm:px-6 lg:px-8 lg:py-0">
          <Link href="/" className="flex items-center gap-2.5 text-base font-semibold text-fg">
            <LogoMark />
            Gene Autoannotator
          </Link>

          <nav aria-label="Main" className="flex flex-wrap gap-1">
            {visibleNavItems.map((item) => {
              const active = isNavItemActive(pathname, item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={`rounded-md px-3 py-2 text-sm font-semibold transition ${
                    active
                      ? "bg-surface-muted text-fg"
                      : "text-fg-muted hover:bg-surface-muted hover:text-fg-secondary"
                  }`}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>

          <div className="ml-auto flex items-center gap-3">
            <ThemeToggle />
            {signedIn ? (
              <Link
                href="/jobs"
                className="workbench-button workbench-button-secondary hidden sm:inline-flex"
              >
                <PlusIcon />
                New job
              </Link>
            ) : null}
            {signedIn || suspended ? (
              <div className="flex items-center gap-3">
                {signedIn ? (
                  <span
                    role="img"
                    aria-label={`Signed in as ${user.email}`}
                    title={user.email}
                    className="grid size-9 place-items-center rounded-full bg-brand-tint-strong text-sm font-semibold text-brand-fg"
                  >
                    {initialsFor(user)}
                  </span>
                ) : null}
                <button
                  type="button"
                  onClick={handleSignOut}
                  disabled={loading}
                  className="text-sm font-semibold text-fg-muted transition hover:text-fg"
                >
                  Sign out
                </button>
              </div>
            ) : null}
          </div>
        </div>
      </header>

      <div className={fullWidth ? "w-full flex-1" : "mx-auto w-full max-w-7xl flex-1 px-6 py-8"}>
        {publicPage ? children : loading ? <SessionLoading /> : suspended ? <SuspendedCard /> : children}
      </div>
      <SiteFooter />
    </main>
  );
}
```

- [ ] **Step 6: Restyle `frontend/components/SiteFooter.js`** — change only class names:
  - `<footer className="border-t workbench-border">` → `<footer className="border-t border-line bg-surface">`
  - the inner div's `workbench-muted` → `text-fg-muted` (keep the other classes)
  - legal links `font-semibold underline-offset-2 hover:underline` → `font-semibold text-fg-secondary underline-offset-2 hover:text-fg hover:underline`

- [ ] **Step 7: Run tests and lint**

Run: `cd frontend && npm test 2>&1 | grep -E '^# (tests|pass|fail)' && npx eslint components/AppShell.js components/ThemeToggle.js components/icons.js components/SiteFooter.js`
Expected: `# fail 0`; ESLint prints nothing.

- [ ] **Step 8: Commit**

```bash
git add frontend/components/icons.js frontend/components/ThemeToggle.js frontend/components/AppShell.js frontend/components/SiteFooter.js frontend/components/AppShell.test.js frontend/components/legal.test.js
git commit -m "feat(frontend): Untitled UI header with light/dark/system switch and full-width shell"
```

---

### Task 3: Re-skin every other page onto tokens

**Files:**
- Create: `frontend/components/designTokens.test.js`
- Modify (class names only, no logic or copy changes): every non-test `.js` file under `frontend/app/` and `frontend/components/` that the guard test flags, **except** `frontend/components/AnnotationExplorer.js` (rewritten in Task 6). Known offenders: `components/JobWorkspace.js`, `components/UserJobsWorkspace.js`, `components/BatchJobForm.js`, `components/FleetDashboard.js`, `components/ProfileWorkspace.js`, `components/SingleJobForm.js`, `components/RegexHelper.js`, `components/CustomFieldsEditor.js`, `components/AuthForms.js`, `components/LegalPlaceholder.js`, `components/QueuePlaceholder.js`, `components/admin/UsersTable.js`, `components/admin/AuditTable.js`, `components/admin/AdminOverview.js`, `components/guide/*.js`, `app/jobs/page.js`, `app/annotations/page.js`, `app/not-found.js`.

**Interfaces:**
- Consumes (Task 1): token utilities and the restyled `workbench-*`/`guide-*` classes.
- Produces: `components/designTokens.test.js` with a `SKIPPED` set that Task 6 empties.

- [ ] **Step 1: Write the guard tests** — create `frontend/components/designTokens.test.js`:

```js
import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

const projectRoot = process.cwd();
const SKIPPED = new Set(["components/AnnotationExplorer.js"]);

const HARD_CODED_COLOUR =
  /\[#[0-9a-fA-F]{3,8}\]|\b(?:bg|text|border|from|to|ring|divide)-(?:slate|gray|zinc|stone|neutral|black)\b[-\w/]*|\bbg-white\b[\w/]*/g;
const OFF_SYSTEM_TYPE_AND_RADIUS =
  /\bfont-(?:bold|extrabold|black)\b|\btracking-\[[^\]]+\]|\buppercase\b|\brounded-(?:2xl|3xl|\[[^\]]+\])/g;

async function sourceFiles(dir) {
  const entries = await readdir(path.join(projectRoot, dir), { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const relative = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...(await sourceFiles(relative)));
    } else if (entry.name.endsWith(".js") && !entry.name.endsWith(".test.js")) {
      files.push(relative);
    }
  }
  return files;
}

async function offenders(pattern) {
  const files = [...(await sourceFiles("app")), ...(await sourceFiles("components"))];
  const found = [];
  for (const file of files) {
    if (SKIPPED.has(file)) continue;
    const source = await readFile(path.join(projectRoot, file), "utf8");
    const hits = source.match(pattern);
    if (hits) found.push(`${file}: ${[...new Set(hits)].join(", ")}`);
  }
  return found;
}

test("components use theme tokens instead of hard-coded colours", async () => {
  assert.deepEqual(await offenders(HARD_CODED_COLOUR), []);
});

test("components stay on the Untitled UI type scale and radii", async () => {
  assert.deepEqual(await offenders(OFF_SYSTEM_TYPE_AND_RADIUS), []);
});
```

- [ ] **Step 2: Run to see every offender**

Run: `cd frontend && node --test components/designTokens.test.js`
Expected: FAIL, listing each file and the offending classes. This list is the work queue.

- [ ] **Step 3: Replace colours using this table** (apply in every flagged file; keep any class that is first in a `className` string first, because some tests anchor on it, for example `className="workbench-amber-bg`):

| Old | New |
|---|---|
| `text-[#3d463f]`, `text-[#3f4b43]` | `text-fg-secondary` |
| `text-[#5a5248]` | `text-fg-tertiary` |
| `hover:text-[#111a16]` | `hover:text-fg` |
| `text-[#f5f0e6]` | `text-fg` |
| `text-[#5f4b2e]`, `text-[#8a7340]` | `text-warning-fg` |
| `text-[#2d4a38]` | `text-success-fg` |
| `text-[#7a3a41]` | `text-error-fg` |
| `text-[#2f4a66]` | `text-info-fg` |
| `bg-[#fffefa]` | `bg-surface` |
| `bg-[#eee6d9]`, `bg-[#e8e3db]`, `bg-[#e3dbcf]` | `bg-surface-sunken` |
| `bg-[#fffaf0]`, `bg-[#f5e8c8]` | `bg-warning-tint` |
| `bg-[#dbe8df]` | `bg-success-tint` |
| `bg-[#f3d9dc]` | `bg-error-tint` |
| `bg-[#dde6f0]` | `bg-info-tint` |
| `bg-[#eef4ef]` | `bg-brand-tint` |
| `bg-[#557864]` | `bg-brand` |
| `bg-[#994f56]` | `bg-error-solid` |
| `bg-[#b9ad99]` | `bg-fg-subtle` |
| `border-[#557864]`, `border-t-[#557864]` | `border-brand-fg`, `border-t-brand-fg` |
| `hover:border-[#557864]` | `hover:border-brand-line` |
| `border-[#d4c4a0]`, `border-[#e3cfa9]` | `border-warning-line` |
| `border-[#b8c7bb]` | `border-success-line` |
| `bg-white/40`, `bg-white/50`, `bg-white/60`, `bg-white/70` | `bg-surface` |
| `bg-black/5` | `bg-surface-sunken` |
| `rounded-3xl border border-white/10 bg-slate-900 p-8 text-slate-300` (Suspense fallbacks in `app/jobs/page.js`, `app/annotations/page.js`) | `workbench-card p-8 text-sm workbench-muted` |

Leave `border-white/40 border-t-white` on the spinner in `RegexHelper.js` (it sits on a brand button) and any `text-white` that sits on `bg-brand`/`bg-error-solid`.

- [ ] **Step 4: Replace typography and radii using this table**

| Old | New |
|---|---|
| `font-bold`, `font-extrabold`, `font-black` | `font-semibold` |
| `tracking-[-0.04em]`, `tracking-[-0.03em]`, `tracking-[-0.02em]`, `tracking-[-0.01em]` | `tracking-tight` |
| `uppercase` together with `tracking-[0.08em]`/`[0.1em]`/`[0.12em]`/`[0.14em]`/`[0.2em]`/`tracking-wide` | delete both (keep the size class, e.g. `text-xs`; make labels `font-medium`) |
| `rounded-2xl`, `rounded-3xl`, `rounded-[18px]` | `rounded-xl` |

- [ ] **Step 5: Run the guard and the full suite**

Run: `cd frontend && node --test components/designTokens.test.js && npm test 2>&1 | grep -E '^# (tests|pass|fail)'`
Expected: guard PASS, `# fail 0`. If a source-pattern test breaks because it pinned an old class string, update only the class portion of that regex.

- [ ] **Step 6: Lint**

Run: `cd frontend && npm run lint`
Expected: exit 0.

- [ ] **Step 7: Commit** (stage the exact files you changed)

```bash
git add frontend/components/designTokens.test.js frontend/components/*.js frontend/components/admin/*.js frontend/components/guide/*.js frontend/app/jobs/page.js frontend/app/annotations/page.js frontend/app/not-found.js
git status --short   # confirm only frontend files are staged
git commit -m "style(frontend): move every page onto theme tokens and the Untitled UI type scale"
```

---

### Task 4: Annotation display helpers

**Files:**
- Create: `frontend/lib/citations.js`, `frontend/lib/citations.test.js`
- Create: `frontend/lib/annotationLayout.js`, `frontend/lib/annotationLayout.test.js`
- Create: `frontend/lib/annotationSummary.js`, `frontend/lib/annotationSummary.test.js`

**Interfaces:**
- Consumes: annotation shape `annotation.generated_at`, `annotation.result.annotation.{annotation_notes, annotation_metadata.{generated_at, field_coverage, gene_name_source, gene_name_source_detail, gene_name_confidence, quality_flags, duration_sec, literature.{papers_analyzed, total_papers_retrieved, sections_analyzed, cumulative_relevance, target_relevance, selected_paper_summaries[{pmc_id, pmid, score, title, year, retrieval_sources, warnings}]}}}`; generated field rows from `getGeneratedFieldRows` (`{ key, label, value: string, orthologDerived, orthologOnly, orthologBlock }`).
- Produces:
  - `splitCitations(text) -> Array<{ type: "text"|"pmid", value: string }>`, `getCitedPmids(...texts) -> string[]`, `pubmedUrl(pmid) -> string`, `pmcUrl(pmcId) -> string`.
  - `NO_DATA = "No supported data"`, `isBooleanValue(value) -> boolean`, `isNoData(value) -> boolean`, `isCompactValue(value) -> boolean`, `planAnnotationGrid(rows) -> { tiles: Array<{ row, span: "full"|"half", lead: boolean }>, compact: row[] }`, `splitListValue(value) -> string[]`.
  - `formatRunTime(seconds) -> string`, `getStatCells(annotation, { locale }?) -> Array<{ key, label, value: string, detail?: string, title?: string, meter?: number }>`, `getFieldCoverage(annotation) -> { supported, total } | null`, `getNameSource(annotation) -> string | null`, `getAnnotationNotes(annotation) -> string`, `getQualityFlags(annotation) -> string[]`, `getPaperMatch(paper) -> { label, tone: "success"|"warning"|"neutral" } | null`, `getSelectedPapers(annotation) -> Array<{ key, pmcId, pmid, title, year, score: number|null, match }>`, `getOrganismOptions(matches) -> string[]`, `filterMatchesByOrganism(matches, organism) -> matches`.

- [ ] **Step 1: Write `frontend/lib/citations.test.js`**

```js
import assert from "node:assert/strict";
import test from "node:test";

import { getCitedPmids, pmcUrl, pubmedUrl, splitCitations } from "./citations.js";

test("splitCitations turns parenthesised PMIDs into citation segments", () => {
  assert.deepEqual(splitCitations("kinetoplast duplication (PMID: 30897087); coordinates mitosis"), [
    { type: "text", value: "kinetoplast duplication " },
    { type: "pmid", value: "30897087" },
    { type: "text", value: "; coordinates mitosis" },
  ]);
});

test("splitCitations expands lists of PMIDs", () => {
  assert.deepEqual(
    splitCitations("(PMID: 1, 22) and (PMIDs: 3; PMID: 4)").filter((s) => s.type === "pmid").map((s) => s.value),
    ["1", "22", "3", "4"],
  );
});

test("splitCitations leaves plain text alone", () => {
  assert.deepEqual(splitCitations("No citations here."), [{ type: "text", value: "No citations here." }]);
  assert.deepEqual(splitCitations(""), []);
  assert.deepEqual(splitCitations(null), []);
});

test("getCitedPmids counts distinct papers across texts", () => {
  assert.deepEqual(getCitedPmids("a (PMID: 19320832)", "b (PMID: 19320832) c (PMID: 30897087)"), [
    "19320832",
    "30897087",
  ]);
});

test("NCBI links", () => {
  assert.equal(pubmedUrl("19320832"), "https://pubmed.ncbi.nlm.nih.gov/19320832/");
  assert.equal(pmcUrl("8550152"), "https://pmc.ncbi.nlm.nih.gov/articles/PMC8550152/");
  assert.equal(pmcUrl("PMC8550152"), "https://pmc.ncbi.nlm.nih.gov/articles/PMC8550152/");
});
```

- [ ] **Step 2: Write `frontend/lib/annotationLayout.test.js`**

```js
import assert from "node:assert/strict";
import test from "node:test";

import { isCompactValue, planAnnotationGrid, splitListValue } from "./annotationLayout.js";

const LONG = "Growth of cultured bloodstream forms is sensitive to Hesperadin (IC50 of 50 nM) (PMID: 19320832).";

function row(key, value) {
  return { key, label: key, value };
}

test("isCompactValue keeps flags, empty values, and short lists compact", () => {
  assert.equal(isCompactValue("True"), true);
  assert.equal(isCompactValue("False"), true);
  assert.equal(isCompactValue("No supported data"), true);
  assert.equal(isCompactValue("Mitosis, Cell cycle, Cytokinesis"), true);
  assert.equal(isCompactValue(LONG), false);
  assert.equal(isCompactValue("Essential in mice."), false);
  assert.equal(isCompactValue("Not essential (PMID: 1)"), false);
  assert.equal(isCompactValue("x".repeat(81)), false);
});

test("planAnnotationGrid leads with the first prose field and pairs the rest", () => {
  const plan = planAnnotationGrid([
    row("functional_category", "Mitosis, Cell cycle"),
    row("function", LONG),
    row("drug_susc_impact", LONG),
    row("infection_impact", LONG),
    row("essential_in_vitro", "True"),
  ]);
  assert.deepEqual(
    plan.tiles.map((tile) => [tile.row.key, tile.span, tile.lead]),
    [
      ["function", "full", true],
      ["drug_susc_impact", "half", false],
      ["infection_impact", "half", false],
    ],
  );
  assert.deepEqual(plan.compact.map((item) => item.key), ["functional_category", "essential_in_vitro"]);
});

test("planAnnotationGrid gives an unpaired last prose field the full width", () => {
  const spans = (count) =>
    planAnnotationGrid(Array.from({ length: count }, (_, index) => row(`f${index}`, LONG))).tiles.map(
      (tile) => tile.span,
    );
  assert.deepEqual(spans(0), []);
  assert.deepEqual(spans(1), ["full"]);
  assert.deepEqual(spans(2), ["full", "full"]);
  assert.deepEqual(spans(4), ["full", "half", "half", "full"]);
});

test("splitListValue splits comma lists", () => {
  assert.deepEqual(splitListValue("Mitosis, Cell cycle ,Cytokinesis"), ["Mitosis", "Cell cycle", "Cytokinesis"]);
  assert.deepEqual(splitListValue("Mitosis"), ["Mitosis"]);
});
```

- [ ] **Step 3: Write `frontend/lib/annotationSummary.test.js`**

```js
import assert from "node:assert/strict";
import test from "node:test";

import {
  filterMatchesByOrganism,
  formatRunTime,
  getAnnotationNotes,
  getFieldCoverage,
  getNameSource,
  getOrganismOptions,
  getPaperMatch,
  getQualityFlags,
  getSelectedPapers,
  getStatCells,
} from "./annotationSummary.js";

function annotationWith(metadata = {}, extra = {}) {
  return {
    generated_at: "2026-05-27T16:54:00Z",
    result: { annotation: { annotation_notes: "  Twelve papers.  ", annotation_metadata: metadata, ...extra } },
  };
}

const LITERATURE = {
  papers_analyzed: 12,
  total_papers_retrieved: 37,
  sections_analyzed: 22,
  cumulative_relevance: 6.961,
  target_relevance: 9,
  selected_paper_summaries: [
    { pmc_id: "1", pmid: "11", score: 0.5, title: "Low", year: 2009, retrieval_sources: ["name"], warnings: ["name_only_match"] },
    { pmc_id: "2", pmid: "22", score: 0.948, title: "High", year: 2021, retrieval_sources: ["locus", "name"], warnings: [] },
  ],
};

test("formatRunTime", () => {
  assert.equal(formatRunTime(45), "45 s");
  assert.equal(formatRunTime(486.2), "8 min");
  assert.equal(formatRunTime(4320), "1 h 12 min");
  assert.equal(formatRunTime(undefined), "—");
});

test("getStatCells summarises the run", () => {
  const cells = getStatCells(
    annotationWith({ literature: LITERATURE, duration_sec: 486.2, quality_flags: [] }),
    { locale: "en-US" },
  );
  const byKey = Object.fromEntries(cells.map((cell) => [cell.key, cell]));
  assert.deepEqual(cells.map((cell) => cell.key), ["generated", "papers", "sections", "relevance", "runtime", "flags"]);
  assert.equal(byKey.generated.value, "May 27, 2026");
  assert.equal(byKey.papers.value, "12");
  assert.equal(byKey.papers.detail, "of 37 retrieved");
  assert.equal(byKey.sections.value, "22");
  assert.equal(byKey.relevance.value, "6.96");
  assert.equal(byKey.relevance.detail, "/ 9.0");
  assert.ok(Math.abs(byKey.relevance.meter - 6.961 / 9) < 1e-9);
  assert.equal(byKey.runtime.value, "8 min");
  assert.equal(byKey.flags.value, "None");
});

test("getStatCells shows a dash for missing values", () => {
  const cells = getStatCells({ result: {} });
  for (const cell of cells) assert.equal(cell.value, "—", cell.key);
  assert.equal(cells.find((cell) => cell.key === "relevance").meter, undefined);
});

test("getStatCells counts quality flags", () => {
  const cells = getStatCells(annotationWith({ quality_flags: ["low_coverage", "conflict"] }));
  assert.equal(cells.find((cell) => cell.key === "flags").value, "2 flagged");
});

test("getFieldCoverage counts supported fields", () => {
  assert.deepEqual(getFieldCoverage(annotationWith({ field_coverage: { a: "supported", b: "unsupported" } })), {
    supported: 1,
    total: 2,
  });
  assert.equal(getFieldCoverage(annotationWith({})), null);
});

test("getNameSource names the database and confidence", () => {
  assert.equal(
    getNameSource(
      annotationWith({
        gene_name_source: "cache",
        gene_name_source_detail: "Cached uniprot: https://rest.uniprot.org/uniprotkb/search",
        gene_name_confidence: "clear",
      }),
    ),
    "UniProt · clear",
  );
  assert.equal(getNameSource(annotationWith({ gene_name_source: "ncbi" })), "NCBI Gene");
  assert.equal(getNameSource(annotationWith({ gene_name_source: "manual" })), "manual");
  assert.equal(getNameSource(annotationWith({})), null);
});

test("notes and quality flags", () => {
  assert.equal(getAnnotationNotes(annotationWith({})), "Twelve papers.");
  assert.equal(getAnnotationNotes({}), "");
  assert.deepEqual(getQualityFlags(annotationWith({ quality_flags: ["a", { code: "b" }] })), ["a", '{"code":"b"}']);
  assert.deepEqual(getQualityFlags(annotationWith({})), []);
});

test("getPaperMatch labels how a paper was found", () => {
  assert.deepEqual(getPaperMatch({ retrieval_sources: ["locus", "name"], warnings: [] }), {
    label: "Locus + name",
    tone: "success",
  });
  assert.deepEqual(getPaperMatch({ retrieval_sources: ["locus"] }), { label: "Locus", tone: "success" });
  assert.deepEqual(getPaperMatch({ retrieval_sources: ["name"], warnings: [] }), { label: "Name", tone: "neutral" });
  assert.deepEqual(getPaperMatch({ retrieval_sources: ["name"], warnings: ["name_only_match"] }), {
    label: "Name only",
    tone: "warning",
  });
  assert.equal(getPaperMatch({}), null);
});

test("getSelectedPapers sorts by relevance", () => {
  const papers = getSelectedPapers(annotationWith({ literature: LITERATURE }));
  assert.deepEqual(papers.map((paper) => paper.title), ["High", "Low"]);
  assert.deepEqual(papers[0], {
    key: "2",
    pmcId: "2",
    pmid: "22",
    title: "High",
    year: 2021,
    score: 0.948,
    match: { label: "Locus + name", tone: "success" },
  });
  assert.deepEqual(getSelectedPapers(annotationWith({})), []);
});

test("organism filter", () => {
  const matches = [
    { id: 1, canonical_name: "Trypanosoma cruzi CL Brener" },
    { id: 2, canonical_name: "Leishmania major Friedlin" },
    { id: 3, canonical_name: "Trypanosoma cruzi CL Brener" },
    { id: 4 },
  ];
  assert.deepEqual(getOrganismOptions(matches), ["Leishmania major Friedlin", "Trypanosoma cruzi CL Brener"]);
  assert.deepEqual(filterMatchesByOrganism(matches, "Leishmania major Friedlin").map((m) => m.id), [2]);
  assert.equal(filterMatchesByOrganism(matches, ""), matches);
});
```

- [ ] **Step 4: Run to verify all three fail**

Run: `cd frontend && node --test lib/citations.test.js lib/annotationLayout.test.js lib/annotationSummary.test.js`
Expected: FAIL — modules not found.

- [ ] **Step 5: Create `frontend/lib/citations.js`**

```js
const CITATION_PATTERN = /\(\s*PMIDs?\s*:?\s*(\d+(?:\s*[,;]\s*(?:PMIDs?\s*:?\s*)?\d+)*)\s*\)/gi;

export function splitCitations(text) {
  const source = text == null ? "" : String(text);
  const segments = [];
  let lastIndex = 0;
  for (const match of source.matchAll(CITATION_PATTERN)) {
    const before = source.slice(lastIndex, match.index);
    if (before) segments.push({ type: "text", value: before });
    for (const pmid of match[1].match(/\d+/g)) {
      segments.push({ type: "pmid", value: pmid });
    }
    lastIndex = match.index + match[0].length;
  }
  const rest = source.slice(lastIndex);
  if (rest) segments.push({ type: "text", value: rest });
  return segments;
}

export function getCitedPmids(...texts) {
  const ids = new Set();
  for (const text of texts) {
    for (const segment of splitCitations(text)) {
      if (segment.type === "pmid") ids.add(segment.value);
    }
  }
  return [...ids];
}

export function pubmedUrl(pmid) {
  return `https://pubmed.ncbi.nlm.nih.gov/${pmid}/`;
}

export function pmcUrl(pmcId) {
  const id = String(pmcId).replace(/^PMC/i, "");
  return `https://pmc.ncbi.nlm.nih.gov/articles/PMC${id}/`;
}
```

- [ ] **Step 6: Create `frontend/lib/annotationLayout.js`**

```js
export const NO_DATA = "No supported data";

const COMPACT_MAX_LENGTH = 80;
const BOOLEAN_VALUES = new Set(["True", "False"]);

export function isBooleanValue(value) {
  return BOOLEAN_VALUES.has(value);
}

export function isNoData(value) {
  return value === NO_DATA;
}

// Flags and short labels fit the side card; anything sentence-like gets a wide tile.
export function isCompactValue(value) {
  const text = String(value ?? "").trim();
  if (!text || isBooleanValue(text) || isNoData(text)) {
    return true;
  }
  return text.length <= COMPACT_MAX_LENGTH && !/[.;:!?](\s|$)/.test(text) && !text.includes("(");
}

export function planAnnotationGrid(rows) {
  const compact = [];
  const prose = [];
  for (const row of rows) {
    (isCompactValue(row.value) ? compact : prose).push(row);
  }
  const pairedCount = prose.length - 1;
  const tiles = prose.map((row, index) => {
    if (index === 0) {
      return { row, span: "full", lead: true };
    }
    const unpaired = pairedCount % 2 === 1 && index === prose.length - 1;
    return { row, span: unpaired ? "full" : "half", lead: false };
  });
  return { tiles, compact };
}

export function splitListValue(value) {
  return String(value ?? "")
    .split(/\s*,\s*/)
    .map((item) => item.trim())
    .filter(Boolean);
}
```

- [ ] **Step 7: Create `frontend/lib/annotationSummary.js`**

```js
const MISSING = "—";

function payloadOf(annotation) {
  return annotation?.result?.annotation || {};
}

function metadataOf(annotation) {
  return payloadOf(annotation).annotation_metadata || {};
}

function literatureOf(annotation) {
  return metadataOf(annotation).literature || {};
}

function isNumber(value) {
  return typeof value === "number" && Number.isFinite(value);
}

export function formatRunTime(seconds) {
  if (!isNumber(seconds)) return MISSING;
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) return `${total} s`;
  const minutes = Math.round(total / 60);
  if (minutes < 60) return `${minutes} min`;
  return `${Math.floor(minutes / 60)} h ${minutes % 60} min`;
}

export function getStatCells(annotation, { locale } = {}) {
  const metadata = metadataOf(annotation);
  const literature = literatureOf(annotation);
  const generatedRaw = annotation?.generated_at || metadata.generated_at;
  const generated = generatedRaw ? new Date(generatedRaw) : null;
  const hasDate = Boolean(generated) && !Number.isNaN(generated.getTime());
  const cumulative = literature.cumulative_relevance;
  const target = literature.target_relevance;
  const flags = metadata.quality_flags;

  return [
    {
      key: "generated",
      label: "Generated",
      value: hasDate
        ? generated.toLocaleDateString(locale, { year: "numeric", month: "short", day: "numeric" })
        : MISSING,
      title: hasDate ? generated.toLocaleString(locale) : undefined,
    },
    {
      key: "papers",
      label: "Papers analyzed",
      value: isNumber(literature.papers_analyzed) ? String(literature.papers_analyzed) : MISSING,
      detail: isNumber(literature.total_papers_retrieved)
        ? `of ${literature.total_papers_retrieved} retrieved`
        : undefined,
    },
    {
      key: "sections",
      label: "Sections",
      value: isNumber(literature.sections_analyzed) ? String(literature.sections_analyzed) : MISSING,
    },
    {
      key: "relevance",
      label: "Relevance",
      value: isNumber(cumulative) ? cumulative.toFixed(2) : MISSING,
      detail: isNumber(target) ? `/ ${target.toFixed(1)}` : undefined,
      meter:
        isNumber(cumulative) && isNumber(target) && target > 0
          ? Math.min(1, Math.max(0, cumulative / target))
          : undefined,
    },
    { key: "runtime", label: "Run time", value: formatRunTime(metadata.duration_sec) },
    {
      key: "flags",
      label: "Quality flags",
      value: Array.isArray(flags) ? (flags.length === 0 ? "None" : `${flags.length} flagged`) : MISSING,
    },
  ];
}

export function getFieldCoverage(annotation) {
  const coverage = metadataOf(annotation).field_coverage;
  if (!coverage || typeof coverage !== "object") return null;
  const values = Object.values(coverage);
  if (values.length === 0) return null;
  return { supported: values.filter((value) => value === "supported").length, total: values.length };
}

export function getNameSource(annotation) {
  const metadata = metadataOf(annotation);
  const source = String(metadata.gene_name_source || "");
  const detail = String(metadata.gene_name_source_detail || "");
  if (!source && !detail) return null;
  let label = source || detail;
  if (/uniprot/i.test(`${source} ${detail}`)) label = "UniProt";
  else if (/ncbi|entrez/i.test(`${source} ${detail}`)) label = "NCBI Gene";
  return metadata.gene_name_confidence ? `${label} · ${metadata.gene_name_confidence}` : label;
}

export function getAnnotationNotes(annotation) {
  const notes = payloadOf(annotation).annotation_notes;
  return typeof notes === "string" ? notes.trim() : "";
}

export function getQualityFlags(annotation) {
  const flags = metadataOf(annotation).quality_flags;
  if (!Array.isArray(flags)) return [];
  return flags.map((flag) => (typeof flag === "string" ? flag : JSON.stringify(flag)));
}

export function getPaperMatch(paper) {
  const sources = Array.isArray(paper?.retrieval_sources) ? paper.retrieval_sources : [];
  const warnings = Array.isArray(paper?.warnings) ? paper.warnings : [];
  if (warnings.includes("name_only_match")) return { label: "Name only", tone: "warning" };
  const byLocus = sources.includes("locus");
  const byName = sources.includes("name");
  if (byLocus && byName) return { label: "Locus + name", tone: "success" };
  if (byLocus) return { label: "Locus", tone: "success" };
  if (byName) return { label: "Name", tone: "neutral" };
  return null;
}

export function getSelectedPapers(annotation) {
  const papers = literatureOf(annotation).selected_paper_summaries;
  if (!Array.isArray(papers)) return [];
  return papers
    .map((paper, index) => ({
      key: String(paper.pmc_id || paper.pmid || index),
      pmcId: paper.pmc_id ? String(paper.pmc_id) : null,
      pmid: paper.pmid ? String(paper.pmid) : null,
      title: paper.title || "Untitled paper",
      year: paper.year ?? null,
      score: isNumber(paper.score) ? paper.score : null,
      match: getPaperMatch(paper),
    }))
    .sort((a, b) => (b.score ?? -1) - (a.score ?? -1));
}

export function getOrganismOptions(matches) {
  const names = new Set();
  for (const match of matches || []) {
    if (match?.canonical_name) names.add(match.canonical_name);
  }
  return [...names].sort((a, b) => a.localeCompare(b));
}

export function filterMatchesByOrganism(matches, organism) {
  if (!organism) return matches;
  return (matches || []).filter((match) => match?.canonical_name === organism);
}
```

- [ ] **Step 8: Run the tests**

Run: `cd frontend && node --test lib/citations.test.js lib/annotationLayout.test.js lib/annotationSummary.test.js && npm test 2>&1 | grep -E '^# (tests|pass|fail)'`
Expected: all PASS; `# fail 0`.

- [ ] **Step 9: Commit**

```bash
git add frontend/lib/citations.js frontend/lib/citations.test.js frontend/lib/annotationLayout.js frontend/lib/annotationLayout.test.js frontend/lib/annotationSummary.js frontend/lib/annotationSummary.test.js
git commit -m "feat(frontend): citation, layout, and summary helpers for the annotation view"
```

---

### Task 5: Annotation tab components

**Files:**
- Create: `frontend/components/annotations/ui.js`
- Create: `frontend/components/annotations/CitedText.js`
- Create: `frontend/components/annotations/PapersTable.js`
- Create: `frontend/components/annotations/OverviewTab.js`
- Create: `frontend/components/annotations/annotations.test.js`

**Interfaces:**
- Consumes: Task 2 icons (`CheckIcon`, `MinusIcon`); Task 4 helpers; `getGeneratedFieldRows`, `getTargetGoTerms` from `lib/annotationDisplay`.
- Produces: `Badge({ tone = "neutral"|"brand"|"success"|"warning", dot = false, title, className = "", children })`, `Card({ as = "section", className = "", children, ...props })`, `CardHeader({ title, aside })`, `Meter({ value: 0..1, className = "" })`, `CitedText({ text })`, `PapersTable({ papers, className = "" })` (papers from `getSelectedPapers`), `OverviewTab({ annotation, profileFields, onViewLiterature })`.

- [ ] **Step 1: Write the source tests** — create `frontend/components/annotations/annotations.test.js`:

```js
import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

const projectRoot = process.cwd();

async function read(file) {
  return readFile(path.join(projectRoot, "components/annotations", file), "utf8");
}

test("OverviewTab places fields with planAnnotationGrid", async () => {
  const overview = await read("OverviewTab.js");
  assert.match(overview, /planAnnotationGrid\(getGeneratedFieldRows\(annotation, profileFields\)\)/);
  assert.match(overview, /full: "col-span-12"/);
  assert.match(overview, /half: "col-span-12 xl:col-span-6"/);
});

test("OverviewTab shows GO terms only when present, as name and id", async () => {
  const overview = await read("OverviewTab.js");
  assert.match(overview, /getTargetGoTerms\(annotation\)/);
  assert.match(overview, /goTerms\.length > 0 \? <GoTermsCard/);
  assert.match(overview, /\{term\.name\}/);
  assert.match(overview, /\{term\.id\}/);
});

test("annotation components never show GO confidence, agreement, or votes", async () => {
  const files = (await readdir(path.join(projectRoot, "components/annotations"))).filter(
    (file) => file.endsWith(".js") && !file.endsWith(".test.js"),
  );
  for (const file of files) {
    assert.doesNotMatch(await read(file), /term\.(agreement|confidence|votes)/, file);
  }
});

test("OverviewTab marks ortholog-derived fields", async () => {
  const overview = await read("OverviewTab.js");
  assert.match(overview, /row\.orthologDerived/);
  assert.match(overview, /"From ortholog"/);
});

test("CitedText links PMIDs to PubMed in a new tab", async () => {
  const cited = await read("CitedText.js");
  assert.match(cited, /splitCitations\(text\)/);
  assert.match(cited, /href=\{pubmedUrl\(segment\.value\)\}/);
  assert.match(cited, /rel="noopener noreferrer"/);
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && node --test components/annotations/annotations.test.js`
Expected: FAIL — files not found.

- [ ] **Step 3: Create `frontend/components/annotations/ui.js`**

```jsx
const BADGE_TONES = {
  neutral: "border-line bg-surface-muted text-fg-secondary",
  brand: "border-brand-line bg-brand-tint text-brand-fg",
  success: "border-success-line bg-success-tint text-success-fg",
  warning: "border-warning-line bg-warning-tint text-warning-fg",
};

export function Badge({ tone = "neutral", dot = false, title, className = "", children }) {
  return (
    <span
      title={title}
      className={`inline-flex max-w-full items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium leading-[18px] ${BADGE_TONES[tone]} ${className}`}
    >
      {dot ? <span aria-hidden="true" className="size-1.5 shrink-0 rounded-full bg-current" /> : null}
      <span className="truncate">{children}</span>
    </span>
  );
}

export function Card({ as: Tag = "section", className = "", children, ...props }) {
  return (
    <Tag className={`min-w-0 rounded-xl border border-line bg-surface shadow-xs ${className}`} {...props}>
      {children}
    </Tag>
  );
}

export function CardHeader({ title, aside = null }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <h3 className="text-sm font-semibold text-fg">{title}</h3>
      {aside}
    </div>
  );
}

export function Meter({ value, className = "" }) {
  const percent = Math.round(Math.min(1, Math.max(0, value)) * 100);
  return (
    <span className={`block h-1.5 flex-1 overflow-hidden rounded-full bg-surface-sunken ${className}`}>
      <span className="block h-full rounded-full bg-brand-fg" style={{ width: `${percent}%` }} />
    </span>
  );
}
```

- [ ] **Step 4: Create `frontend/components/annotations/CitedText.js`**

```jsx
import { pubmedUrl, splitCitations } from "../../lib/citations";

export default function CitedText({ text }) {
  return (
    <>
      {splitCitations(text).map((segment, index) =>
        segment.type === "pmid" ? (
          <a
            key={index}
            href={pubmedUrl(segment.value)}
            target="_blank"
            rel="noopener noreferrer"
            className="mx-0.5 whitespace-nowrap rounded-md border border-brand-tint-strong bg-brand-tint px-1.5 py-px font-mono text-[13px] text-brand-fg transition hover:border-brand-line"
          >
            PMID {segment.value}
          </a>
        ) : (
          <span key={index}>{segment.value}</span>
        ),
      )}
    </>
  );
}
```

- [ ] **Step 5: Create `frontend/components/annotations/PapersTable.js`**

```jsx
import { pmcUrl, pubmedUrl } from "../../lib/citations";
import { Badge, Meter } from "./ui";

export default function PapersTable({ papers, className = "" }) {
  return (
    <div className={`overflow-x-auto ${className}`}>
      <table className="w-full min-w-[640px] border-collapse text-sm">
        <thead>
          <tr className="border-y border-line bg-surface-muted text-left text-xs text-fg-muted">
            <th scope="col" className="px-6 py-2.5 font-medium">Title</th>
            <th scope="col" className="px-4 py-2.5 font-medium">Year</th>
            <th scope="col" className="px-4 py-2.5 font-medium">Relevance</th>
            <th scope="col" className="px-4 py-2.5 font-medium">Match</th>
            <th scope="col" className="px-6 py-2.5 font-medium">PMID</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {papers.map((paper) => (
            <tr key={paper.key}>
              <td className="w-3/5 max-w-0 px-6 py-3">
                {paper.pmcId ? (
                  <a
                    href={pmcUrl(paper.pmcId)}
                    target="_blank"
                    rel="noopener noreferrer"
                    title={paper.title}
                    className="block truncate font-medium text-fg hover:text-brand-fg"
                  >
                    {paper.title}
                  </a>
                ) : (
                  <span title={paper.title} className="block truncate font-medium text-fg">
                    {paper.title}
                  </span>
                )}
              </td>
              <td className="px-4 py-3 text-fg-tertiary">{paper.year ?? "—"}</td>
              <td className="px-4 py-3 text-fg-tertiary">
                {paper.score != null ? (
                  <span className="flex items-center gap-2.5">
                    <Meter value={paper.score} className="max-w-24" />
                    {paper.score.toFixed(2)}
                  </span>
                ) : (
                  "—"
                )}
              </td>
              <td className="px-4 py-3">
                {paper.match ? <Badge tone={paper.match.tone}>{paper.match.label}</Badge> : "—"}
              </td>
              <td className="px-6 py-3 font-mono text-fg-tertiary">
                {paper.pmid ? (
                  <a
                    href={pubmedUrl(paper.pmid)}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="hover:text-brand-fg"
                  >
                    {paper.pmid}
                  </a>
                ) : (
                  "—"
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 6: Create `frontend/components/annotations/OverviewTab.js`**

```jsx
import { getGeneratedFieldRows, getTargetGoTerms } from "../../lib/annotationDisplay";
import { isBooleanValue, isNoData, planAnnotationGrid, splitListValue } from "../../lib/annotationLayout";
import { getAnnotationNotes, getQualityFlags, getSelectedPapers } from "../../lib/annotationSummary";
import { getCitedPmids } from "../../lib/citations";
import { CheckIcon, MinusIcon } from "../icons";
import CitedText from "./CitedText";
import PapersTable from "./PapersTable";
import { Badge, Card, CardHeader } from "./ui";

const TILE_SPAN = { full: "col-span-12", half: "col-span-12 xl:col-span-6" };
const PREVIEW_PAPER_COUNT = 4;

function CitesHint({ text }) {
  const count = getCitedPmids(text).length;
  if (count === 0) return null;
  return (
    <span className="shrink-0 text-xs text-fg-muted">
      Cites {count} paper{count === 1 ? "" : "s"}
    </span>
  );
}

function ProvenanceBadge({ row }) {
  if (!row.orthologDerived) return null;
  const source = row.orthologBlock?.sourceLabel;
  const prefix = row.orthologOnly ? "From ortholog" : "Target + ortholog";
  return (
    <Badge tone="warning" title={source || undefined}>
      {source ? `${prefix}: ${source}` : prefix}
    </Badge>
  );
}

function FieldTile({ tile }) {
  const { row, span, lead } = tile;
  return (
    <Card className={`${TILE_SPAN[span]} px-6 py-5`}>
      <CardHeader
        title={row.label}
        aside={
          <span className="flex min-w-0 items-center gap-2">
            <ProvenanceBadge row={row} />
            <CitesHint text={row.value} />
          </span>
        }
      />
      <p
        className={`mt-2.5 max-w-[110ch] whitespace-pre-wrap text-fg-secondary ${
          lead ? "text-base leading-[26px]" : "text-[15px] leading-6"
        }`}
      >
        <CitedText text={row.value} />
      </p>
    </Card>
  );
}

function CompactValue({ value }) {
  if (value === "True") {
    return (
      <span className="inline-flex items-center gap-1.5">
        <CheckIcon className="text-success-solid" />
        Yes
      </span>
    );
  }
  if (value === "False") {
    return (
      <span className="inline-flex items-center gap-1.5 text-fg-secondary">
        <MinusIcon className="text-fg-subtle" />
        No
      </span>
    );
  }
  if (isNoData(value)) {
    return <span className="font-normal text-fg-subtle">{value}</span>;
  }
  return (
    <span className="flex flex-wrap gap-1.5">
      {splitListValue(value).map((item) => (
        <Badge key={item} tone="brand">
          {item}
        </Badge>
      ))}
    </span>
  );
}

function ClassificationCard({ rows }) {
  return (
    <Card className="px-6 py-5">
      <CardHeader title="Classification" />
      <dl className="mt-3 grid gap-3 text-sm">
        {rows.map((row) => (
          <div
            key={row.key}
            className={
              isBooleanValue(row.value) || isNoData(row.value)
                ? "flex items-center justify-between gap-4"
                : "grid gap-2"
            }
          >
            <dt className="text-fg-muted">{row.label}</dt>
            <dd className="font-medium text-fg">
              <CompactValue value={row.value} />
            </dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}

function GoTermsCard({ terms }) {
  return (
    <Card className="px-6 py-5">
      <CardHeader
        title="Gene Ontology"
        aside={
          <span className="text-xs text-fg-muted">
            {terms.length} term{terms.length === 1 ? "" : "s"}
          </span>
        }
      />
      <ul className="mt-2 divide-y divide-line text-sm">
        {terms.map((term, index) => (
          <li key={`${term.id}-${index}`} className="flex items-baseline justify-between gap-3 py-2">
            <span className="text-fg-secondary">{term.name}</span>
            <span className="shrink-0 font-mono text-xs text-fg-muted">{term.id}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function NotesCard({ notes, flags, className }) {
  return (
    <Card className={`${className} px-6 py-5`}>
      <CardHeader
        title="Annotation notes"
        aside={
          flags.length > 0 ? (
            <span className="flex flex-wrap justify-end gap-1.5">
              {flags.map((flag, index) => (
                <Badge key={`${flag}-${index}`} tone="warning" dot>
                  {flag}
                </Badge>
              ))}
            </span>
          ) : (
            <CitesHint text={notes} />
          )
        }
      />
      <p className="mt-2.5 max-w-[110ch] whitespace-pre-wrap text-[15px] leading-6 text-fg-secondary">
        <CitedText text={notes} />
      </p>
    </Card>
  );
}

export default function OverviewTab({ annotation, profileFields, onViewLiterature }) {
  const { tiles, compact } = planAnnotationGrid(getGeneratedFieldRows(annotation, profileFields));
  const goTerms = getTargetGoTerms(annotation);
  const notes = getAnnotationNotes(annotation);
  const flags = getQualityFlags(annotation);
  const papers = getSelectedPapers(annotation);
  const sideCards = [
    compact.length > 0 ? <ClassificationCard key="classification" rows={compact} /> : null,
    goTerms.length > 0 ? <GoTermsCard key="go" terms={goTerms} /> : null,
  ].filter(Boolean);

  return (
    <div className="grid grid-cols-12 gap-5">
      {tiles.map((tile) => (
        <FieldTile key={tile.row.key} tile={tile} />
      ))}

      {notes ? (
        <>
          <NotesCard
            notes={notes}
            flags={flags}
            className={sideCards.length > 0 ? "col-span-12 xl:col-span-8" : "col-span-12"}
          />
          {sideCards.length > 0 ? (
            <div className="col-span-12 flex flex-col gap-5 xl:col-span-4">{sideCards}</div>
          ) : null}
        </>
      ) : (
        sideCards.map((card) => (
          <div key={card.key} className={sideCards.length > 1 ? "col-span-12 xl:col-span-6" : "col-span-12"}>
            {card}
          </div>
        ))
      )}

      {papers.length > 0 ? (
        <Card className="col-span-12 overflow-hidden">
          <div className="px-6 pt-5">
            <CardHeader
              title="Selected papers"
              aside={
                papers.length > PREVIEW_PAPER_COUNT ? (
                  <button
                    type="button"
                    onClick={onViewLiterature}
                    className="text-sm font-semibold text-brand-fg hover:underline"
                  >
                    View all {papers.length} →
                  </button>
                ) : null
              }
            />
          </div>
          <PapersTable papers={papers.slice(0, PREVIEW_PAPER_COUNT)} className="mt-3" />
        </Card>
      ) : null}
    </div>
  );
}
```

Note: the "GO only when present" test expects the literal `goTerms.length > 0 ? <GoTermsCard`, which the `sideCards` array above contains.

- [ ] **Step 7: Run tests and lint**

Run: `cd frontend && node --test components/annotations/annotations.test.js && npm test 2>&1 | grep -E '^# (tests|pass|fail)' && npx eslint components/annotations`
Expected: PASS; `# fail 0`; no ESLint output.

- [ ] **Step 8: Commit**

```bash
git add frontend/components/annotations/ui.js frontend/components/annotations/CitedText.js frontend/components/annotations/PapersTable.js frontend/components/annotations/OverviewTab.js frontend/components/annotations/annotations.test.js
git commit -m "feat(frontend): annotation tab grid with wide prose tiles, classification, GO, and papers"
```

---

### Task 6: Two-pane annotations page

**Files:**
- Create: `frontend/components/annotations/ResultsRail.js`
- Create: `frontend/components/annotations/AnnotationHeader.js`
- Create: `frontend/components/annotations/StatStrip.js`
- Create: `frontend/components/annotations/AnnotationTabs.js`
- Create: `frontend/components/annotations/LiteratureTab.js`
- Create: `frontend/components/annotations/VersionsTab.js`
- Create: `frontend/components/annotations/OrthologTab.js`
- Create: `frontend/components/annotations/MetadataTab.js`
- Create: `frontend/components/annotations/AnnotationDetail.js`
- Modify: `frontend/components/AnnotationExplorer.js` (full rewrite)
- Modify: `frontend/app/annotations/page.js` (`<AppShell>` → `<AppShell fullWidth>`)
- Modify: `frontend/components/AnnotationExplorer.test.js` (full rewrite)
- Modify: `frontend/components/annotations/annotations.test.js` (append)
- Modify: `frontend/components/legal.test.js:192-195` (disclaimer now in `AnnotationHeader.js`)
- Modify: `frontend/lib/annotationRoutes.test.js:56-61` (job IDs now in `MetadataTab.js`/`VersionsTab.js`)
- Modify: `frontend/components/designTokens.test.js` (empty `SKIPPED`)

**Interfaces:**
- Consumes: Task 2 icons and `AppShell fullWidth`; Task 4 helpers; Task 5 `Badge`, `Card`, `CardHeader`, `Meter`, `CitedText`, `PapersTable`, `OverviewTab`; existing `lib/api`, `lib/annotationMatches`, `lib/annotationVersions`, `lib/annotationDisplay`, `lib/form`, `lib/legal`, `lib/profileStore`.
- Produces: `AnnotationExplorer({ initialQuery, initialMatches, initialMessage })` (unchanged props).

- [ ] **Step 1: Rewrite the tests**

Replace `frontend/components/AnnotationExplorer.test.js` with:

```js
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

const projectRoot = process.cwd();

function read(file) {
  return readFile(path.join(projectRoot, file), "utf8");
}

test("AnnotationExplorer lays out a results rail beside the detail pane", async () => {
  const explorer = await read("components/AnnotationExplorer.js");
  assert.match(explorer, /lg:grid-cols-\[320px_minmax\(0,1fr\)\]/);
  assert.match(explorer, /<ResultsRail/);
  assert.match(explorer, /<AnnotationDetail/);
  assert.match(explorer, /filterMatchesByOrganism\(matches, organism\)/);
});

test("selecting a result opens the Annotation tab", async () => {
  const explorer = await read("components/AnnotationExplorer.js");
  assert.match(explorer, /async function loadAnnotation\(annotationId\) \{[\s\S]*?setActiveTab\("annotation"\)/);
});

test("ortholog content gets its own tab only when the annotation has it", async () => {
  const detail = await read("components/annotations/AnnotationDetail.js");
  assert.match(detail, /const showOrtholog = hasOrthologColumn\(view\)/);
  assert.match(detail, /showOrtholog \? \[\{ id: "ortholog", label: "Ortholog" \}\] : \[\]/);
  const ortholog = await read("components/annotations/OrthologTab.js");
  assert.match(ortholog, /getOrthologGoTerms\(annotation\)/);
  assert.match(ortholog, /\.filter\(\(row\) => row\.orthologDerived\)/);
  assert.match(ortholog, /goTerms\.length > 0 \?/);
  assert.match(ortholog, /\{formatGoTermLabel\(term\)\}/);
});

test("annotations page uses the full-width shell", async () => {
  const page = await read("app/annotations/page.js");
  assert.match(page, /<AppShell fullWidth>/);
});
```

Append to `frontend/components/annotations/annotations.test.js`:

```js
test("tabs follow the WAI-ARIA tabs pattern", async () => {
  const tabs = await read("AnnotationTabs.js");
  assert.match(tabs, /role="tablist"/);
  assert.match(tabs, /role="tab"/);
  assert.match(tabs, /aria-selected=\{selected\}/);
  assert.match(tabs, /tabIndex=\{selected \? 0 : -1\}/);
  assert.match(tabs, /ArrowRight/);
  const detail = await read("AnnotationDetail.js");
  assert.match(detail, /role="tabpanel"/);
});

test("results rail focuses search on Cmd/Ctrl-K and keeps the submit-a-gene path", async () => {
  const rail = await read("ResultsRail.js");
  assert.match(rail, /\(event\.metaKey \|\| event\.ctrlKey\) && event\.key\.toLowerCase\(\) === "k"/);
  assert.match(rail, /href=\{`\/jobs\?locus=\$\{encodeURIComponent\(searchedQuery\)\}`\}/);
  assert.match(rail, /Submit this gene for annotation/);
});

test("disclaimer can be hidden for the browser session only", async () => {
  const header = await read("AnnotationHeader.js");
  assert.match(header, /sessionStorage/);
  assert.doesNotMatch(header, /localStorage/);
});

test("re-run is offered only on the latest version", async () => {
  const header = await read("AnnotationHeader.js");
  assert.match(header, /!viewingHistorical \? \(\s*<Link\s+href=\{buildJobPrefillHref\(annotation\)\}/);
});
```

In `frontend/components/legal.test.js` replace the three `explorer` assertions (lines 192–195) with:

```js
  const header = await readProjectFile("components/annotations/AnnotationHeader.js");
  assert.match(header, /import \{ RESEARCH_DISCLAIMER \} from "\.\.\/\.\.\/lib\/legal"/);
  assert.match(header, /\{RESEARCH_DISCLAIMER\}/);
  assert.match(header, /href="\/legal\/disclaimer"/);
```

In `frontend/lib/annotationRoutes.test.js` replace the body of `"AnnotationExplorer hides job ids when the API omits them"` with:

```js
  const metadata = await readProjectFile("components/annotations/MetadataTab.js");
  const versions = await readProjectFile("components/annotations/VersionsTab.js");
  assert.match(metadata, /\{annotation\.job_id \? \(/);
  assert.match(versions, /\{option\.job_id \? ` · job \$\{option\.job_id\}` : ""\}/);
  assert.doesNotMatch(metadata + versions, /job_id \|\| "Unknown"/);
```

In `frontend/components/designTokens.test.js` change `new Set(["components/AnnotationExplorer.js"])` to `new Set()`.

- [ ] **Step 2: Run to verify they fail**

Run: `cd frontend && npm test 2>&1 | grep -E '^not ok|^# (pass|fail)'`
Expected: the rewritten tests fail (missing files / old markup).

- [ ] **Step 3: Create `frontend/components/annotations/ResultsRail.js`**

```jsx
"use client";

import Link from "next/link";
import { useEffect, useRef, useSyncExternalStore } from "react";

import { SearchIcon } from "../icons";

const subscribeNever = () => () => {};
const isApplePlatform = () => /Mac|iPhone|iPad/.test(navigator.platform);

function versionLabel(match) {
  const count = (match.version_count || 0) + 1;
  return `${count} version${count === 1 ? "" : "s"}`;
}

export default function ResultsRail({
  query,
  onQueryChange,
  onSearch,
  isSearching,
  message,
  searchedQuery,
  totalCount,
  organisms,
  organism,
  onOrganismChange,
  matches,
  hiddenCount,
  onShowAll,
  selectedId,
  onSelect,
}) {
  const inputRef = useRef(null);
  const apple = useSyncExternalStore(subscribeNever, isApplePlatform, () => true);

  useEffect(() => {
    function onKeyDown(event) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        inputRef.current?.focus();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <aside className="flex flex-col border-b border-line bg-surface lg:sticky lg:top-16 lg:h-[calc(100vh-4rem)] lg:border-r lg:border-b-0">
      <div className="border-b border-line px-4 pt-5 pb-3">
        <form
          role="search"
          onSubmit={(event) => {
            event.preventDefault();
            onSearch();
          }}
        >
          <label htmlFor="annotation-search" className="sr-only">
            Search annotations
          </label>
          <div className="flex h-10 items-center gap-2 rounded-lg border border-line-strong bg-surface px-3 text-fg-muted shadow-xs focus-within:border-brand-line focus-within:ring-4 focus-within:ring-focus-ring">
            <SearchIcon size={18} />
            <input
              id="annotation-search"
              ref={inputRef}
              value={query}
              onChange={(event) => onQueryChange(event.target.value)}
              placeholder="Locus, gene name, or term"
              className="min-w-0 flex-1 bg-transparent text-sm text-fg outline-none placeholder:text-fg-subtle"
            />
            {isSearching ? (
              <span className="text-xs text-fg-muted">Searching…</span>
            ) : (
              <kbd className="rounded border border-line px-1 font-sans text-xs text-fg-subtle">
                {apple ? "⌘K" : "Ctrl K"}
              </kbd>
            )}
          </div>
        </form>
        {message ? (
          <p className="mt-3 text-sm text-warning-fg" role="status">
            {message}
          </p>
        ) : null}
        {searchedQuery ? (
          <div className="mt-3 flex items-center justify-between gap-2 text-xs text-fg-muted">
            <span>
              {totalCount} result{totalCount === 1 ? "" : "s"}
            </span>
            {organisms.length > 1 ? (
              <label className="flex min-w-0 items-center">
                <span className="sr-only">Filter by organism</span>
                <select
                  value={organism}
                  onChange={(event) => onOrganismChange(event.target.value)}
                  className="max-w-44 truncate bg-transparent font-semibold text-fg-secondary outline-none"
                >
                  <option value="">All organisms</option>
                  {organisms.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
          </div>
        ) : null}
      </div>

      <div className="max-h-80 overflow-y-auto p-2 lg:max-h-none lg:flex-1">
        {!searchedQuery ? (
          <p className="px-3 py-6 text-sm text-fg-muted">
            Search by locus, gene name, or organism to find stored annotations.
          </p>
        ) : null}

        {searchedQuery && totalCount === 0 && !isSearching ? (
          <div className="px-3 py-6">
            <p className="text-sm font-semibold text-fg">No annotation found</p>
            <p className="mt-1 text-sm text-fg-muted">
              Nothing stored matches “{searchedQuery}” yet. Submit it as a new job and come back when it
              finishes.
            </p>
            <Link
              href={`/jobs?locus=${encodeURIComponent(searchedQuery)}`}
              className="workbench-button workbench-button-primary mt-4"
            >
              Submit this gene for annotation
            </Link>
          </div>
        ) : null}

        <ul className="grid gap-0.5">
          {matches.map((match) => {
            const isSelected = match.id === selectedId;
            return (
              <li key={match.id}>
                <button
                  type="button"
                  onClick={() => onSelect(match.id)}
                  aria-current={isSelected ? "true" : undefined}
                  className={`block w-full rounded-lg border px-3 py-2.5 text-left transition ${
                    isSelected ? "border-brand-line bg-brand-tint" : "border-transparent hover:bg-surface-muted"
                  }`}
                >
                  <span className="flex items-baseline justify-between gap-2">
                    <span className="truncate font-semibold text-fg">
                      {match.gene_name || match.normalized_locus}
                    </span>
                    <span className="shrink-0 text-xs text-fg-muted">{versionLabel(match)}</span>
                  </span>
                  <span className="mt-0.5 block truncate text-xs text-fg-muted">
                    <span className="font-mono text-fg-secondary">{match.normalized_locus}</span> ·{" "}
                    {match.canonical_name}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>

        {hiddenCount > 0 ? (
          <button
            type="button"
            onClick={onShowAll}
            className="mt-1 w-full rounded-lg px-3 py-2 text-left text-sm font-semibold text-brand-fg hover:bg-surface-muted"
          >
            Show {hiddenCount} more
          </button>
        ) : null}
      </div>

      <p className="mt-auto hidden border-t border-line px-4 py-3 text-xs text-fg-muted lg:block">
        Not finding a gene?{" "}
        <Link href="/jobs" className="font-semibold text-brand-fg">
          Submit it for annotation →
        </Link>
      </p>
    </aside>
  );
}
```

- [ ] **Step 4: Create `frontend/components/annotations/AnnotationHeader.js`**

```jsx
"use client";

import Link from "next/link";
import { useState } from "react";

import { getFieldCoverage, getNameSource } from "../../lib/annotationSummary";
import { buildVersionOptions, CURRENT_VERSION_KEY, getTotalVersionCount } from "../../lib/annotationVersions";
import { buildJobPrefillHref } from "../../lib/form";
import { RESEARCH_DISCLAIMER } from "../../lib/legal";
import { AlertIcon, ChevronDownIcon, CloseIcon, RefreshIcon } from "../icons";
import { Badge } from "./ui";

const DISCLAIMER_HIDDEN_KEY = "ga-disclaimer-hidden";

function readDisclaimerHidden() {
  try {
    return window.sessionStorage.getItem(DISCLAIMER_HIDDEN_KEY) === "1";
  } catch {
    return false;
  }
}

export default function AnnotationHeader({ annotation, view, versions, selectedVersionKey, onSelectVersion }) {
  const [disclaimerHidden, setDisclaimerHidden] = useState(readDisclaimerHidden);
  const options = buildVersionOptions(annotation, versions);
  const total = getTotalVersionCount(annotation, versions);
  const selected = options.find((option) => option.key === selectedVersionKey) || options[0];
  const viewingHistorical = selectedVersionKey !== CURRENT_VERSION_KEY;
  const coverage = getFieldCoverage(view);
  const nameSource = getNameSource(view);
  const geneName = view.gene_name || annotation.normalized_locus;

  function hideDisclaimer() {
    window.sessionStorage.setItem(DISCLAIMER_HIDDEN_KEY, "1");
    setDisclaimerHidden(true);
  }

  return (
    <header>
      <nav aria-label="Breadcrumb" className="flex flex-wrap items-center gap-2 text-sm font-medium text-fg-muted">
        <span>Annotations</span>
        <span aria-hidden="true">/</span>
        <span>{annotation.canonical_name}</span>
        <span aria-hidden="true">/</span>
        <span aria-current="page" className="font-semibold text-brand-fg">
          {geneName}
        </span>
      </nav>

      <div className="mt-4 flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div className="min-w-0">
          <h1 className="flex flex-wrap items-baseline gap-x-3 text-3xl font-semibold tracking-tight text-fg">
            {geneName}
            <span className="font-mono text-base font-normal tracking-normal text-fg-muted">
              {annotation.normalized_locus}
            </span>
          </h1>
          <div className="mt-2 flex flex-wrap gap-2">
            {annotation.canonical_name ? <Badge tone="brand">{annotation.canonical_name}</Badge> : null}
            {viewingHistorical ? (
              <Badge tone="warning" dot>
                Older version {selected.versionNumber} of {total}
              </Badge>
            ) : (
              <Badge dot>
                Latest · version {total} of {total}
              </Badge>
            )}
            {coverage ? (
              <Badge tone={coverage.supported === coverage.total ? "success" : "warning"} dot>
                {coverage.supported === coverage.total
                  ? `All ${coverage.total} fields supported`
                  : `${coverage.supported} of ${coverage.total} fields supported`}
              </Badge>
            ) : null}
            {nameSource ? <Badge>Name: {nameSource}</Badge> : null}
          </div>
        </div>

        <div className="flex shrink-0 flex-wrap gap-3">
          {total > 1 ? (
            <label className="relative">
              <span className="sr-only">Version</span>
              <select
                value={selectedVersionKey}
                onChange={(event) => onSelectVersion(event.target.value)}
                className="workbench-button workbench-button-secondary cursor-pointer appearance-none pr-9"
              >
                {options.map((option) => (
                  <option key={option.key} value={option.key}>
                    Version {option.versionNumber}
                    {option.isCurrent ? " (latest)" : ""}
                  </option>
                ))}
              </select>
              <ChevronDownIcon className="pointer-events-none absolute top-1/2 right-3 -translate-y-1/2 text-fg-muted" />
            </label>
          ) : null}
          {!viewingHistorical ? (
            <Link
              href={buildJobPrefillHref(annotation)}
              className="workbench-button workbench-button-primary"
            >
              <RefreshIcon />
              Re-run annotation
            </Link>
          ) : null}
        </div>
      </div>

      {!disclaimerHidden ? (
        <div
          role="note"
          className="mt-5 flex items-start gap-3 rounded-lg border border-warning-line bg-warning-tint px-3.5 py-2.5 text-sm text-warning-fg"
        >
          <AlertIcon size={18} className="mt-px" />
          <p className="flex-1">
            {RESEARCH_DISCLAIMER}{" "}
            <Link href="/legal/disclaimer" className="font-semibold underline underline-offset-2">
              Read the disclaimer
            </Link>
          </p>
          <button
            type="button"
            onClick={hideDisclaimer}
            aria-label="Hide the disclaimer for this session"
            className="rounded p-0.5 transition hover:bg-warning-line"
          >
            <CloseIcon />
          </button>
        </div>
      ) : null}

      {viewingHistorical ? (
        <div
          role="status"
          className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line bg-surface-muted px-3.5 py-2.5 text-sm text-fg-secondary"
        >
          <span>You are viewing an older saved version.</span>
          <button
            type="button"
            onClick={() => onSelectVersion(CURRENT_VERSION_KEY)}
            className="font-semibold text-brand-fg hover:underline"
          >
            Back to latest
          </button>
        </div>
      ) : null}
    </header>
  );
}
```

- [ ] **Step 5: Create `frontend/components/annotations/StatStrip.js`**

```jsx
import { getStatCells } from "../../lib/annotationSummary";
import { Meter } from "./ui";

export default function StatStrip({ annotation }) {
  return (
    <dl className="mt-5 grid grid-cols-2 overflow-hidden rounded-xl border border-line bg-surface shadow-xs sm:grid-cols-3 xl:grid-cols-6">
      {getStatCells(annotation).map((cell) => (
        <div key={cell.key} title={cell.title} className="-mb-px -ml-px border-b border-l border-line px-4 py-3">
          <dt className="text-xs font-medium text-fg-muted">{cell.label}</dt>
          <dd className="mt-0.5 flex items-center gap-2 whitespace-nowrap font-semibold text-fg">
            {cell.value}
            {cell.detail ? <span className="text-xs font-normal text-fg-muted">{cell.detail}</span> : null}
            {cell.meter != null ? <Meter value={cell.meter} className="max-w-[72px]" /> : null}
          </dd>
        </div>
      ))}
    </dl>
  );
}
```

- [ ] **Step 6: Create `frontend/components/annotations/AnnotationTabs.js`**

```jsx
"use client";

import { useRef } from "react";

const KEY_OFFSETS = { ArrowRight: 1, ArrowLeft: -1 };

export default function AnnotationTabs({ tabs, active, onChange }) {
  const tabRefs = useRef({});

  function onKeyDown(event, index) {
    let next = null;
    if (event.key in KEY_OFFSETS) next = (index + KEY_OFFSETS[event.key] + tabs.length) % tabs.length;
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = tabs.length - 1;
    if (next === null) return;
    event.preventDefault();
    onChange(tabs[next].id);
    tabRefs.current[tabs[next].id]?.focus();
  }

  return (
    <div role="tablist" aria-label="Annotation sections" className="mt-6 flex gap-6 overflow-x-auto border-b border-line">
      {tabs.map((tab, index) => {
        const selected = tab.id === active;
        return (
          <button
            key={tab.id}
            ref={(node) => {
              tabRefs.current[tab.id] = node;
            }}
            type="button"
            role="tab"
            id={`annotation-tab-${tab.id}`}
            aria-selected={selected}
            aria-controls={`annotation-panel-${tab.id}`}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(tab.id)}
            onKeyDown={(event) => onKeyDown(event, index)}
            className={`-mb-px flex shrink-0 items-center gap-2 border-b-2 px-1 pb-3 text-sm font-semibold transition ${
              selected
                ? "border-brand-fg text-brand-fg"
                : "border-transparent text-fg-muted hover:border-line-strong hover:text-fg-secondary"
            }`}
          >
            {tab.label}
            {tab.count != null ? (
              <span
                className={`rounded-full px-2 text-xs font-medium leading-[18px] ${
                  selected ? "bg-brand-tint text-brand-fg" : "bg-surface-sunken text-fg-secondary"
                }`}
              >
                {tab.count}
              </span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 7: Create `frontend/components/annotations/LiteratureTab.js`**

```jsx
import { getPmcIdsAnalyzed } from "../../lib/annotationDisplay";
import { getSelectedPapers } from "../../lib/annotationSummary";
import { pmcUrl } from "../../lib/citations";
import PapersTable from "./PapersTable";
import { Card, CardHeader } from "./ui";

export default function LiteratureTab({ annotation }) {
  const papers = getSelectedPapers(annotation);
  const pmcIds = getPmcIdsAnalyzed(annotation);

  return (
    <div className="grid gap-5">
      <Card className="overflow-hidden">
        <div className="px-6 pt-5">
          <CardHeader title="Selected papers" aside={<span className="text-xs text-fg-muted">Ranked by relevance</span>} />
        </div>
        {papers.length > 0 ? (
          <PapersTable papers={papers} className="mt-3" />
        ) : (
          <p className="px-6 pt-2 pb-5 text-sm text-fg-muted">No paper summaries were stored with this annotation.</p>
        )}
      </Card>

      <Card className="px-6 py-5">
        <CardHeader title="PMC IDs analyzed" aside={<span className="text-xs text-fg-muted">{pmcIds.length}</span>} />
        {pmcIds.length > 0 ? (
          <ul className="mt-3 flex flex-wrap gap-2">
            {pmcIds.map((pmcId) => (
              <li key={pmcId}>
                <a
                  href={pmcUrl(pmcId)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-block rounded-md border border-line bg-surface-muted px-2 py-0.5 font-mono text-xs text-fg-secondary transition hover:border-brand-line hover:text-brand-fg"
                >
                  PMC{pmcId}
                </a>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-sm text-fg-muted">No analyzed PMC IDs stored.</p>
        )}
      </Card>
    </div>
  );
}
```

- [ ] **Step 8: Create `frontend/components/annotations/VersionsTab.js`**

```jsx
import { buildVersionOptions } from "../../lib/annotationVersions";
import { Badge, Card } from "./ui";

export default function VersionsTab({
  annotation,
  versions,
  selectedVersionKey,
  onSelectVersion,
  onLoadVersions,
  isLoadingVersions,
}) {
  const hasOlderVersions = (annotation.version_count || 0) > 0;

  if (hasOlderVersions && !versions) {
    return (
      <Card className="px-6 py-5">
        <p className="text-sm text-fg-muted">
          {isLoadingVersions ? "Loading version history…" : "Version history has not been loaded."}
        </p>
        {!isLoadingVersions ? (
          <button type="button" onClick={onLoadVersions} className="workbench-button workbench-button-secondary mt-4">
            Load version history
          </button>
        ) : null}
      </Card>
    );
  }

  return (
    <Card className="overflow-hidden">
      <ul className="divide-y divide-line">
        {buildVersionOptions(annotation, versions).map((option) => {
          const isSelected = option.key === selectedVersionKey;
          const generated = option.generated_at ? new Date(option.generated_at).toLocaleString() : "Unknown";
          return (
            <li key={option.key}>
              <button
                type="button"
                onClick={() => onSelectVersion(option.key)}
                aria-current={isSelected ? "true" : undefined}
                className={`flex w-full flex-wrap items-center gap-x-6 gap-y-1 px-6 py-4 text-left text-sm transition ${
                  isSelected ? "bg-brand-tint" : "hover:bg-surface-muted"
                }`}
              >
                <span className="flex min-w-40 items-center gap-2 font-semibold text-fg">
                  Version {option.versionNumber}
                  {option.isCurrent ? <Badge tone="brand">Latest</Badge> : null}
                </span>
                <span className="text-fg-secondary">
                  {option.gene_name || annotation.gene_name || annotation.normalized_locus}
                </span>
                <span className="text-fg-muted">
                  Generated {generated}
                  {option.job_id ? ` · job ${option.job_id}` : ""}
                </span>
                {isSelected ? <span className="ml-auto text-xs font-semibold text-brand-fg">Viewing</span> : null}
              </button>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
```

- [ ] **Step 9: Create `frontend/components/annotations/OrthologTab.js`**

```jsx
import { formatGoTermLabel, getGeneratedFieldRows, getOrthologGoTerms } from "../../lib/annotationDisplay";
import CitedText from "./CitedText";
import { Card, CardHeader } from "./ui";

export default function OrthologTab({ annotation, profileFields }) {
  const rows = getGeneratedFieldRows(annotation, profileFields).filter((row) => row.orthologDerived);
  const goTerms = getOrthologGoTerms(annotation);

  return (
    <div className="grid gap-5">
      {rows.length > 0 ? (
        <Card className="overflow-hidden">
          <div className="px-6 pt-5">
            <CardHeader title="Target and ortholog evidence" />
          </div>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[720px] border-collapse text-sm">
              <thead>
                <tr className="border-y border-line bg-surface-muted text-left text-xs text-fg-muted">
                  <th scope="col" className="w-48 px-6 py-2.5 font-medium">Field</th>
                  <th scope="col" className="px-4 py-2.5 font-medium">Target</th>
                  <th scope="col" className="px-6 py-2.5 font-medium">Ortholog</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line align-top">
                {rows.map((row) => (
                  <tr key={row.key}>
                    <th scope="row" className="px-6 py-4 text-left font-semibold text-fg">
                      {row.label}
                    </th>
                    <td className="px-4 py-4 leading-6 text-fg-secondary">
                      {row.orthologOnly ? (
                        <span className="text-fg-subtle">No target data</span>
                      ) : (
                        <CitedText text={row.value} />
                      )}
                    </td>
                    <td className="px-6 py-4 leading-6 text-fg-secondary">
                      <CitedText text={row.orthologOnly ? row.value : row.orthologBlock?.value || "No supported data"} />
                      {row.orthologBlock?.sourceLabel ? (
                        <p className="mt-2 text-xs font-medium text-warning-fg">From {row.orthologBlock.sourceLabel}</p>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ) : null}

      {goTerms.length > 0 ? (
        <Card className="px-6 py-5">
          <CardHeader title="Ortholog Gene Ontology terms" />
          <ul className="mt-2 divide-y divide-line text-sm text-fg-secondary">
            {goTerms.map((term, index) => (
              <li key={`${term.id}-${index}`} className="py-2">
                {formatGoTermLabel(term)}
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
    </div>
  );
}
```

- [ ] **Step 10: Create `frontend/components/annotations/MetadataTab.js`**

```jsx
import { getMetadataRows } from "../../lib/annotationDisplay";
import { Card } from "./ui";

function Item({ label, mono = false, children }) {
  return (
    <div className="min-w-0">
      <dt className="text-fg-muted">{label}</dt>
      <dd className={`mt-1 whitespace-pre-wrap break-words text-fg ${mono ? "font-mono" : "font-medium"}`}>
        {children}
      </dd>
    </div>
  );
}

export default function MetadataTab({ annotation }) {
  const rows = getMetadataRows(annotation).filter((row) => row.key !== "annotation_notes");
  return (
    <Card className="px-6 py-5">
      <dl className="grid gap-x-8 gap-y-5 text-sm sm:grid-cols-2 xl:grid-cols-3">
        {annotation.job_id ? (
          <Item label="Job" mono>
            {annotation.job_id}
          </Item>
        ) : null}
        {annotation.profile_id ? (
          <Item label="Profile" mono>
            {annotation.profile_id}
          </Item>
        ) : null}
        {rows.map((row) => (
          <Item key={row.key} label={row.label}>
            {row.value}
          </Item>
        ))}
      </dl>
    </Card>
  );
}
```

- [ ] **Step 11: Create `frontend/components/annotations/AnnotationDetail.js`**

```jsx
"use client";

import { hasOrthologColumn } from "../../lib/annotationDisplay";
import { getSelectedPapers } from "../../lib/annotationSummary";
import { annotationViewForVersion, getTotalVersionCount } from "../../lib/annotationVersions";
import AnnotationHeader from "./AnnotationHeader";
import AnnotationTabs from "./AnnotationTabs";
import LiteratureTab from "./LiteratureTab";
import MetadataTab from "./MetadataTab";
import OrthologTab from "./OrthologTab";
import OverviewTab from "./OverviewTab";
import StatStrip from "./StatStrip";
import { Card } from "./ui";
import VersionsTab from "./VersionsTab";

function EmptyDetail() {
  return (
    <div className="grid min-h-80 place-items-center rounded-xl border border-dashed border-line-strong p-10 text-center">
      <div>
        <p className="text-base font-semibold text-fg">No annotation selected</p>
        <p className="mt-1 max-w-md text-sm text-fg-muted">
          Search by locus, gene name, or organism, then pick a result to read its annotation.
        </p>
      </div>
    </div>
  );
}

export default function AnnotationDetail({
  annotation,
  profileFields,
  versions,
  selectedVersionKey,
  onSelectVersion,
  onLoadVersions,
  isLoadingVersions,
  activeTab,
  onTabChange,
}) {
  if (!annotation) {
    return <EmptyDetail />;
  }

  const view = annotationViewForVersion(annotation, selectedVersionKey, versions);
  const totalVersions = getTotalVersionCount(annotation, versions);
  const paperCount = getSelectedPapers(view).length;
  const showOrtholog = hasOrthologColumn(view);
  const tabs = [
    { id: "annotation", label: "Annotation" },
    { id: "literature", label: "Literature", count: paperCount || undefined },
    { id: "versions", label: "Versions", count: totalVersions },
    ...(showOrtholog ? [{ id: "ortholog", label: "Ortholog" }] : []),
    { id: "metadata", label: "Metadata" },
    { id: "raw", label: "Raw JSON" },
  ];
  const current = tabs.some((tab) => tab.id === activeTab) ? activeTab : "annotation";

  function selectVersion(key) {
    onSelectVersion(key);
    onTabChange("annotation");
  }

  return (
    <article className="mx-auto min-w-0 max-w-[105rem]">
      <AnnotationHeader
        annotation={annotation}
        view={view}
        versions={versions}
        selectedVersionKey={selectedVersionKey}
        onSelectVersion={onSelectVersion}
      />
      <StatStrip annotation={view} />
      <AnnotationTabs tabs={tabs} active={current} onChange={onTabChange} />
      <div
        role="tabpanel"
        id={`annotation-panel-${current}`}
        aria-labelledby={`annotation-tab-${current}`}
        tabIndex={0}
        className="mt-6 outline-none"
      >
        {current === "annotation" ? (
          <OverviewTab
            annotation={view}
            profileFields={profileFields}
            onViewLiterature={() => onTabChange("literature")}
          />
        ) : null}
        {current === "literature" ? <LiteratureTab annotation={view} /> : null}
        {current === "versions" ? (
          <VersionsTab
            annotation={annotation}
            versions={versions}
            selectedVersionKey={selectedVersionKey}
            onSelectVersion={selectVersion}
            onLoadVersions={onLoadVersions}
            isLoadingVersions={isLoadingVersions}
          />
        ) : null}
        {current === "ortholog" ? <OrthologTab annotation={view} profileFields={profileFields} /> : null}
        {current === "metadata" ? <MetadataTab annotation={view} /> : null}
        {current === "raw" ? (
          <Card className="overflow-hidden">
            <pre className="annotation-raw-json max-h-[70vh] p-5 font-mono text-xs leading-5 text-fg-secondary">
              {JSON.stringify(view.result, null, 2)}
            </pre>
          </Card>
        ) : null}
      </div>
    </article>
  );
}
```

- [ ] **Step 12: Rewrite `frontend/components/AnnotationExplorer.js`**

```jsx
"use client";

import { useState } from "react";

import { getAnnotation, getAnnotationVersions, getProfile, searchAnnotations } from "../lib/api";
import { getHiddenMatchCount, getVisibleMatches } from "../lib/annotationMatches";
import { filterMatchesByOrganism, getOrganismOptions } from "../lib/annotationSummary";
import { CURRENT_VERSION_KEY } from "../lib/annotationVersions";
import { resolveProfileFieldsForDisplay } from "../lib/profileStore";
import AnnotationDetail from "./annotations/AnnotationDetail";
import ResultsRail from "./annotations/ResultsRail";

export default function AnnotationExplorer({ initialQuery = "", initialMatches = [], initialMessage = "" }) {
  const [query, setQuery] = useState(initialQuery);
  const [matches, setMatches] = useState(initialMatches);
  const [selected, setSelected] = useState(null);
  const [profileFields, setProfileFields] = useState(null);
  const [versions, setVersions] = useState(null);
  const [selectedVersionKey, setSelectedVersionKey] = useState(CURRENT_VERSION_KEY);
  const [isLoadingVersions, setIsLoadingVersions] = useState(false);
  const [message, setMessage] = useState(initialMessage);
  const [searchedQuery, setSearchedQuery] = useState(initialQuery);
  const [isSearching, setIsSearching] = useState(false);
  const [showAllMatches, setShowAllMatches] = useState(false);
  const [organism, setOrganism] = useState("");
  const [activeTab, setActiveTab] = useState("annotation");

  const filteredMatches = filterMatchesByOrganism(matches, organism);
  const hiddenMatchCount = showAllMatches ? 0 : getHiddenMatchCount(filteredMatches);
  const visibleMatches = getVisibleMatches(filteredMatches, showAllMatches);

  async function fetchVersions(annotationId) {
    setIsLoadingVersions(true);
    try {
      const payload = await getAnnotationVersions(annotationId);
      setVersions(payload.versions || []);
    } catch (error) {
      setMessage(error.message);
    } finally {
      setIsLoadingVersions(false);
    }
  }

  async function runSearch(nextQuery = query) {
    const trimmed = nextQuery.trim();
    if (!trimmed) {
      setMessage("Enter a locus, gene name, or organism-related term.");
      return;
    }

    setIsSearching(true);
    setMessage("");
    setSelected(null);
    setProfileFields(null);
    setVersions(null);
    setSelectedVersionKey(CURRENT_VERSION_KEY);
    setSearchedQuery(trimmed);
    setShowAllMatches(false);
    setOrganism("");

    try {
      const payload = await searchAnnotations(trimmed);
      setMatches(payload.matches || []);
    } catch (error) {
      setMatches([]);
      setMessage(error.message);
    } finally {
      setIsSearching(false);
    }
  }

  async function loadAnnotation(annotationId) {
    setMessage("");
    setVersions(null);
    setProfileFields(null);
    setSelectedVersionKey(CURRENT_VERSION_KEY);
    setActiveTab("annotation");

    try {
      const annotation = await getAnnotation(annotationId);
      setSelected(annotation);
      if (annotation.profile_id) {
        try {
          const profile = await getProfile(annotation.profile_id);
          setProfileFields(resolveProfileFieldsForDisplay(profile));
        } catch {
          // Fall back to the hard-coded field list when the profile is unavailable.
          setProfileFields(null);
        }
      }
      if ((annotation.version_count || 0) > 0) {
        await fetchVersions(annotationId);
      }
    } catch (error) {
      setMessage(error.message);
    }
  }

  async function loadVersions() {
    if (!selected) return;
    await fetchVersions(selected.id);
  }

  return (
    <div className="grid min-h-[calc(100vh-4rem)] lg:grid-cols-[320px_minmax(0,1fr)]">
      <ResultsRail
        query={query}
        onQueryChange={setQuery}
        onSearch={() => runSearch()}
        isSearching={isSearching}
        message={message}
        searchedQuery={searchedQuery}
        totalCount={filteredMatches.length}
        organisms={getOrganismOptions(matches)}
        organism={organism}
        onOrganismChange={(value) => {
          setOrganism(value);
          setShowAllMatches(false);
        }}
        matches={visibleMatches}
        hiddenCount={hiddenMatchCount}
        onShowAll={() => setShowAllMatches(true)}
        selectedId={selected?.id}
        onSelect={loadAnnotation}
      />
      <div className="min-w-0 px-4 py-6 sm:px-6 lg:px-8">
        <AnnotationDetail
          annotation={selected}
          profileFields={profileFields}
          versions={versions}
          selectedVersionKey={selectedVersionKey}
          onSelectVersion={setSelectedVersionKey}
          onLoadVersions={loadVersions}
          isLoadingVersions={isLoadingVersions}
          activeTab={activeTab}
          onTabChange={setActiveTab}
        />
      </div>
    </div>
  );
}
```

- [ ] **Step 13: Use the full-width shell** — in `frontend/app/annotations/page.js` change `<AppShell>` to `<AppShell fullWidth>` (the Suspense fallback was already restyled in Task 3).

- [ ] **Step 14: Run tests and lint**

Run: `cd frontend && npm test 2>&1 | grep -E '^not ok|^# (tests|pass|fail)' && npm run lint`
Expected: `# fail 0`; lint exit 0.

- [ ] **Step 15: Commit**

```bash
git add frontend/components/annotations frontend/components/AnnotationExplorer.js frontend/components/AnnotationExplorer.test.js frontend/app/annotations/page.js frontend/components/legal.test.js frontend/lib/annotationRoutes.test.js frontend/components/designTokens.test.js
git commit -m "feat(frontend): two-pane annotations page with results rail, stat strip, and tabs"
```

---

### Task 7: Visual verification and polish (controller)

**Files:**
- Temporary, never committed: `frontend/app/design-preview/page.js`, `frontend/app/design-preview/PreviewClient.js`
- Modify only if the screenshots show a defect: any file from Tasks 1–6

- [ ] **Step 1: Build** — `cd frontend && npm run build` (needs network for Google Fonts). Expected: build succeeds.

- [ ] **Step 2: Preview harness** — create `frontend/app/design-preview/PreviewClient.js`, a client component that renders `ResultsRail` with a few static matches and `AnnotationDetail` with a fixture shaped like the API response (`{ id, gene_name, normalized_locus, canonical_name, generated_at, version_count: 0, job_id, profile_id, result: { annotation: <contents of gen_json/tcruzi-clbrener/v2_gen_TcCLB.503799.4.json> } }`), holding `activeTab` in state; and `frontend/app/design-preview/page.js` rendering it inside `<AppShell publicPage fullWidth>`. If `frontend/middleware.js` redirects the path, add the route to its public list only in the working tree.

- [ ] **Step 3: Screenshots** — run `npm run dev` and capture with headless Chrome at 1600×1600, 1280×1900 and 390×2400, for `?` default and with `localStorage["ga-theme"]` set to `dark` (for example via a `?theme=dark` branch in the preview client that writes the key before rendering). Also capture `/`, `/login`, and `/legal/disclaimer` in both themes. Check: no light-only surfaces in dark mode, no overflowing text, prose tiles are wide, the stat strip does not wrap awkwardly, focus rings are visible.

- [ ] **Step 4: Fix defects** in the owning file, rerun `npm test` and `npm run lint`, and commit each fix with a `fix(frontend): …` message.

- [ ] **Step 5: Delete the harness** — `rm -r frontend/app/design-preview` and revert any middleware edit; `git status --short` must show only the user's pre-existing files.
