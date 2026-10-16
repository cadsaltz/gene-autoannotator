# Blind needle labeling (consensus-arms Phase 2)

You are labeling ONE excerpt to establish gold "needles": the facts an ideal, rule-following extractor
should find about the TARGET gene. You have **not** seen any model output and must not look for any
(do not open `results/`, `labels/`, or other stubs). Do not call tools. Return JSON only.

## Input

```json
{STUB_JSON}
```

Use `gene_id`, `gene_name`, and `profile_id` (organism) to identify the TARGET gene. Identify it by locus id
OR gene/protein name or obvious synonyms (e.g. murG = MurG glycosyltransferase; Rv1617 = pykA = pyruvate
kinase). The `excerpt_text` is the only text you may use.

## Rules (same as the extractor prompt and `results/model_spread_15k/labels/RUBRIC.md`)

- Use ONLY the excerpt. Only facts about the TARGET gene; ignore other genes.
- No inference from gene class, pathway, or general/organism knowledge. Null/absent when not explicitly supported.
- Do not summarize the paper, section, methods, results overview, or pathway panel.
- Booleans (`essential_in_vitro`, `essential_in_vivo`) only with direct experimental evidence in the excerpt
  (deletion, transposon, CRISPRi, knockdown...). Otherwise absent.
- Be fair: if the excerpt clearly states the target gene's function/phenotype, mark it present even if it
  seems hard to find. Be strict: no credit for plausible-but-unstated biology.

## Fields

Label every field below. For `mtb-h37rv` omit `essential_in_vitro` and `essential_in_vivo` (4 fields);
for all other organisms label all 6.

- `function`: gene-specific mechanism/role of the gene product, one or two concise sentences; whether it
  performs vs regulates a process. Not a paper/section summary.
- `functional_category`: list of short GO-oriented tags (about 2-6 words each, e.g. "regulation of
  translation"); one concept per item; no IDs or sentences; prefer few high-confidence tags.
- `drug_susc_impact`: explicitly reported effect on the organism's drug susceptibility (1-2 sentences).
- `infection_impact`: explicitly reported effect on infection (1-2 sentences).
- `essential_in_vitro`: `true`/`false` only with direct experimental evidence in the excerpt.
- `essential_in_vivo`: `true`/`false` only with direct experimental evidence in the excerpt.

For each field give:

- `gold_status`: `"present"` if the excerpt explicitly supports a value about the TARGET gene, else `"absent"`.
- `gold_value`: short ideal answer (string / list / true / false), or `null` when absent.
- `gold_quote`: short VERBATIM quote (<= 200 chars) copied from `excerpt_text` that supports it, or `null`.
  Join non-adjacent fragments with `...`. The quote must be found in the excerpt (whitespace aside).

## Output

Return a single JSON object with exactly this shape (same as the stub, with `fields` filled):

```json
{
  "trial_id": "<copy from input>",
  "fields": {
    "function": {"gold_status": "present|absent", "gold_value": "... or null", "gold_quote": "... or null"},
    "functional_category": {"gold_status": "present|absent", "gold_value": ["..."], "gold_quote": "... or null"},
    "drug_susc_impact": {"gold_status": "...", "gold_value": null, "gold_quote": null},
    "infection_impact": {"gold_status": "...", "gold_value": null, "gold_quote": null},
    "essential_in_vitro": {"gold_status": "...", "gold_value": null, "gold_quote": null},
    "essential_in_vivo": {"gold_status": "...", "gold_value": null, "gold_quote": null}
  },
  "excerpt_note": "<= 40 words: what the excerpt is about and how much it says about the target gene"
}
```

For absent `functional_category`, use `"gold_value": null`. Include no keys other than those shown. Do not
add `needs_human`; the merge step sets it when double-labelers disagree.
