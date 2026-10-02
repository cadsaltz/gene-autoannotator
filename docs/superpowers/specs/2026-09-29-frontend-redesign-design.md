# Frontend redesign: Untitled UI foundations, wide annotations layout, dark mode

**Status:** design approved 2026-09-29 (mockup), with the condition that the site gets a
user-selectable dark mode.

**Mockup:** [`2026-09-29-frontend-redesign/annotations-redesign.html`](2026-09-29-frontend-redesign/annotations-redesign.html)
(light and dark screenshots alongside it). The mockup is the visual source of truth for the
annotations page; this document records the decisions behind it and how they generalize.

## Goal

Make the frontend look deliberately designed instead of improvised, without changing what it
does. Cosmetic only: no API, data, auth, or routing changes.

1. Re-skin the whole site on one public design system's foundations.
2. Re-lay-out the annotations page so text gets room and secondary facts are condensed.
3. Add light / dark / system theme selection, available on every page.

## Reference: Untitled UI

[Untitled UI](https://www.untitledui.com/) (Jordan Hughes) is the single reference. Its React
component library ([untitleduico/react](https://github.com/untitleduico/react)) is MIT-licensed;
we use only its *foundations*, re-implemented in our CSS. We do not copy components or
install the library.

| Foundation | Value |
|---|---|
| Font | Inter (text), Roboto Mono (IDs, loci, PMIDs, JSON), via `next/font/google` |
| Text scale | xs 12/18, sm 14/20, md 16/24, lg 18/28, xl 20/30; display xs 24/32, sm 30/38 |
| Light grays | 25 `#FCFCFD` · 50 `#F9FAFB` · 100 `#F2F4F7` · 200 `#EAECF0` · 300 `#D0D5DD` · 400 `#98A2B3` · 500 `#667085` · 600 `#475467` · 700 `#344054` · 800 `#1D2939` · 900 `#101828` |
| Dark grays | 950 `#0C111D` · 900 `#161B26` · 800 `#1F242F` · 700 `#333741` · 500 `#85888E` · 400 `#94969C` · 300 `#CECFD2` · 200 `#ECECED` · 50 `#F5F5F6` |
| Brand | Tailwind teal (Untitled UI's theming swaps its default purple for any palette): 25 `#F5FDFB` … 600 `#0D9488` · 700 `#0F766E` |
| Status | Untitled UI warning (amber), success (green), error (red) scales |
| Radius | md 6px (chips, small buttons) · lg 8px (buttons, inputs, list rows) · xl 12px (cards) |
| Shadow | xs `0 1px 2px rgba(16,24,40,.05)`; sm for popovers |

What keeps it ours: the teal brand, the logo mark, and domain elements Untitled UI does not
have (PMID citation chips, relevance meters, paper match badges, ortholog comparison).

## Theming architecture

- `app/globals.css` defines **semantic tokens** as CSS variables, once for light and once under
  `[data-theme="dark"]`: page background, surface, surface-muted, border, border-strong,
  text-primary / secondary / tertiary, brand (solid, text, tint, tint-border), warning, success,
  error (each text, tint, tint-border). Components only reference semantic tokens, so dark mode
  needs no per-component rules.
- Tokens are exposed to Tailwind through `@theme inline` (for example `bg-surface`,
  `text-secondary`, `border-line`) so components use utilities instead of hex values.
- The existing `workbench-*` classes stay as the shared component vocabulary (card, button,
  input, kicker, muted, …) but are restyled onto the tokens. This re-skins every page at once
  and keeps the change reviewable.
- Every hard-coded colour in components (about 75 `[#hex]` utilities plus a few `slate-*`,
  `white/70`, etc.) is replaced with a token utility, so nothing stays light in dark mode.

### Theme selection

- Choices: **Light, Dark, System**; default **System** (`prefers-color-scheme`).
- Control: a compact three-icon segmented switch (sun / moon / monitor) in the header, visible
  on every page, signed in or not. Buttons have `aria-pressed` and accessible labels.
- Persistence: `localStorage["ga-theme"]`. No account setting (cosmetic, per device).
- No flash: a tiny inline script in `app/layout.js` sets `data-theme` on `<html>` before first
  paint; `<html suppressHydrationWarning>`. System mode follows OS changes live.
- `color-scheme` is set per theme so native controls and scrollbars match.

## Site-wide shell

- **Header:** 64px, surface background, bottom border, sticky. Logo mark + "Gene
  Autoannotator"; nav links as Untitled UI "header nav" items (gray text, active item on a
  muted background); right side: theme switch, a "New job" secondary button (signed-in users
  who can submit; links to `/jobs`), and the account (initials avatar with email in its title,
  plus Sign out). Existing role-aware nav logic (`navItemsFor`, `isNavItemActive`) is unchanged.
  The subtitle line is dropped.
- **Width:** `AppShell` gains a `fullWidth` prop. The annotations page uses it (edge-to-edge);
  every other page keeps the current centred `max-w-7xl` content width.
- **Footer** and auth/legal/admin/jobs/profiles/fleet/guide pages: re-skinned through tokens
  only; their layouts do not change. The guide hero's dark-green gradient becomes a brand-tinted
  surface that works in both themes.

## Annotations page

Two-pane, full width (at `lg` and up):

```
┌ header ─────────────────────────────────────────────────────────────┐
├ results rail (320px, sticky) ┬ detail (fills the rest) ─────────────┤
│ search input (⌘/Ctrl-K)      │ breadcrumbs                           │
│ N results · organism filter  │ gene + locus · badges · actions       │
│ compact result rows          │ disclaimer notice (one line)          │
│ …                            │ stat strip (6 cells)                  │
│ "Not finding a gene?" link   │ tabs                                  │
│                              │ tab content                           │
└──────────────────────────────┴──────────────────────────────────────┘
```

Below `lg` the rail stacks above the detail (not sticky, list capped in height).

### Results rail

- Search input submits on Enter (same `runSearch` behaviour). ⌘K / Ctrl-K focuses it.
- Meta line: result count and an **organism filter** (client-side, over the distinct
  `canonical_name` values of the current matches; "All organisms" default). Hidden when there
  is only one organism.
- Rows: gene name, version count, mono locus · organism; the selected row uses the brand tint.
  The existing "show more" behaviour (`getVisibleMatches` / `getHiddenMatchCount`) becomes a
  "Show N more" row at the end of the list.
- Empty / no-results / error states live in the rail; the no-results state keeps the "Submit
  this gene for annotation" link (`/jobs?locus=…`). Footer link "Submit it for annotation" goes
  to `/jobs`.
- Nothing selected: the detail pane shows a quiet empty state ("Select a result…").

### Detail header

- Breadcrumbs: Annotations / organism / gene.
- Title: gene name (display sm) + mono locus.
- Badges: organism (brand); version ("Latest · version N of N", or a warning badge "Older
  version k of N" when viewing history); field coverage from `annotation_metadata.field_coverage`
  ("All 6 fields supported" success, or "4 of 6 fields supported" warning; hidden if absent);
  name source (`gene_name_source` + confidence, hidden if absent).
- Actions: version picker (native `<select>` styled as a secondary button; loads versions on
  first open if they were not loaded) and primary **Re-run annotation** (the existing
  `buildJobPrefillHref` link, hidden when viewing an older version).
- Research disclaimer: one-line warning notice with the "Read the disclaimer" link. Its close
  button hides it for the browser session only (`sessionStorage`), so it returns on the next
  visit. The "viewing an older version" notice appears below it when relevant.

### Stat strip

Six cells: Generated (date; time in its tooltip), Papers analyzed ("12 of 37 retrieved"),
Sections, Relevance (cumulative / target with a meter), Run time, Quality flags ("None" or a
count). Missing values show "—". On narrow screens it wraps to 3 then 2 columns. The job ID
moves to the Metadata tab.

### Tabs

Annotation · Literature (count) · Versions (count) · Ortholog (only when `hasOrthologColumn`)
· Metadata · Raw JSON. Proper `tablist`/`tab`/`tabpanel` ARIA with arrow-key navigation.
Selecting another result resets to the Annotation tab.

**Annotation tab** uses a 12-column grid. Fields are profile-defined, so placement is computed,
not hard-coded:

- Each generated field row is classified as **compact** (booleans, "No supported data", and
  short lists or phrases with no sentence punctuation, under about 80 characters) or **prose**.
- Prose fields: the first spans 12 columns; the rest pair up at 6 + 6; an odd one out spans 12.
  Prose renders at 16/26 (first) or 15/24, max line length about 110 characters.
- Annotation notes (from metadata) span 8 columns, with a 4-column side stack of:
  - **Classification**: compact fields. Lists render as brand chips, booleans as Yes / No with
    an icon, "No supported data" in tertiary text.
  - **Gene Ontology**: term name + mono GO ID (no confidence or agreement values, matching the
    current rule). Hidden when empty.
  If there are no notes, the side cards share a row at 6 + 6 (or one at 12).
- Ortholog-derived fields keep their provenance as a warning badge in the card header
  ("From ortholog: Tb927… · T. brucei · 82% identity") instead of tinting the whole card.
- Citations: `(PMID: 123)` and `(PMID: 123, 456)` in prose render as mono chips linking to
  PubMed (new tab). The card hint shows "Cites N papers" (distinct PMIDs) when N > 0.
- **Selected papers** card (12 columns): the top 4 of
  `literature.selected_paper_summaries` by score, with "View all N" switching to the
  Literature tab. Hidden when there are no summaries.

The mockup's "Conflict resolved" badge has no structured source in the data, so it is not
built. Quality flags (when present) show as warning badges on the notes card instead.

**Literature tab:** the full selected-papers table: title (links to the PMC article), year,
relevance meter (score 0–1), match badge from `retrieval_sources` (Locus + name / Locus /
Name) with `name_only_match` warnings shown as a warning "Name only" badge, PMID link. Below
it, the existing "PMC IDs analyzed" list as a compact chip grid.

**Versions tab:** the current version-history behaviour (load button, list, select to view)
as a table-like list with a "Latest" badge; selecting a version switches back to the
Annotation tab.

**Ortholog tab:** one comparison table instead of two cramped columns: Field | Target |
Ortholog (with source label), then ortholog GO terms. Full width.

**Metadata tab:** a two-column description list of the existing metadata rows plus job ID and
profile ID.

**Raw JSON tab:** the existing pretty-printed JSON in a mono, scrollable code panel.

## Non-goals

- No changes to the API, search behaviour, data shape, auth, roles, or routes.
- No re-layout of pages other than annotations (they are re-skinned only).
- No new dependencies besides the Inter and Roboto Mono fonts through `next/font`.
- No account-level theme preference.

## Testing and verification

- Pure helpers get `node --test` unit tests: field classification and grid placement, PMID
  citation parsing, paper match labels, stat formatting, theme resolution (stored choice +
  system preference → applied theme).
- Existing source-pattern tests that pin old markup (for example the two-column ortholog
  layout in `AnnotationExplorer.test.js`) are rewritten for the new structure while keeping
  their intent (GO list hides when empty and never shows confidence; ortholog content only
  appears when `hasOrthologColumn`).
- `npm test`, `npm run lint`, and `npm run build` pass.
- Visual check: headless-Chrome screenshots of the annotations page (with real stored data)
  and a sample of other pages, in light and dark, at 1600px and 1280px, plus a narrow mobile
  width. Contrast of text tokens meets WCAG AA in both themes.

## Delivery

Work on a feature branch, review, show the user screenshots of the real pages, then merge to
`master` (merging is pre-authorized; no PR needed).
