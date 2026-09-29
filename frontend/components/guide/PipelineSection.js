const KICKER = "How the pipeline works";
const TITLE = "From a gene identifier to a review-ready annotation";
const INTRO =
  "Every job runs the same nine stages on a compute worker. Most of the time goes into the language-model steps, because every excerpt is read by several models.";

const STAGES = [
  {
    title: "Gene resolution",
    short: "Gene",
    text: "Your organism profile plus a gene name, a locus, or both is resolved to one target. A missing name is filled in from the profile's annotation table, a local cache, NCBI Gene, or UniProt.",
  },
  {
    title: "Literature retrieval (PubMed/PMC)",
    short: "Papers",
    text: "PubMed Central is searched for the locus and, when known, the gene name in titles and abstracts, with a PubMed-to-PMC fallback. Full-text articles are downloaded and cached.",
  },
  {
    title: "Relevance filtering",
    short: "Filter",
    text: "Each paper is scored with organism and gene relevance rules. Top-ranked papers are kept until their combined relevance reaches a target of 9.0, with at least 5 and at most 20 papers; if only a handful are eligible, all of them are used and the result is flagged.",
  },
  {
    title: "Section excerpting",
    short: "Excerpts",
    text: "The abstract, results, and discussion are pulled from each paper. Long sections are split into excerpts of at most 6,000 characters, and very long ones are narrowed to passages around mentions of the gene.",
  },
  {
    title: "Multi-model summaries",
    short: "Extract",
    text: "Each excerpt goes to several independent summary models (three, from different model families, in the default mode). Each returns structured JSON for the annotation fields.",
  },
  {
    title: "Consensus",
    short: "Agree",
    text: "For each excerpt, values that at least half of the extractors agree on are kept by fixed rules. Remaining disagreements go to a consensus model whose answer must trace back to the candidates and the excerpt text; malformed or wrong-gene output is dropped.",
  },
  {
    title: "Aggregation",
    short: "Combine",
    text: "An aggregation model merges the per-excerpt results across papers into one gene-level annotation, citing PMIDs and writing notes about conflicts, gaps, and how strong the literature is.",
  },
  {
    title: "GO term resolution",
    short: "GO",
    text: "If the organism profile enables it, the function text and categories are matched against the Gene Ontology. Candidates are shortlisted by exact, alias, and embedding matches, then the models vote; terms with majority support are kept.",
  },
  {
    title: "Stored annotation",
    short: "Save",
    text: "The annotation is saved with metadata on paper selection, quality flags, field coverage, and run time. Annotating the same gene again adds a new version and keeps the older ones.",
  },
];

const ORTHOLOG_TITLE = "Optional: ortholog fallback";
const ORTHOLOG_TEXT =
  "When you allow it on a job and the gene's own literature falls short of the relevance target, the pipeline can look up a related gene in another profiled organism (via KEGG SSDB) and run the same paper stages on it. Only fields the profile allows are filled this way, and they are labeled as ortholog-derived in the viewer.";

export default function PipelineSection() {
  return (
    <section id="pipeline" aria-labelledby="pipeline-title" className="scroll-mt-6">
      <p className="workbench-kicker">{KICKER}</p>
      <h2 id="pipeline-title" className="workbench-foreground mt-2 text-3xl font-bold tracking-[-0.04em]">
        {TITLE}
      </h2>
      <p className="workbench-muted mt-3 max-w-2xl leading-7">{INTRO}</p>

      <div
        aria-hidden="true"
        className="workbench-card mt-6 flex items-center gap-2 overflow-x-auto p-4 text-xs font-bold"
      >
        {STAGES.map((stage, index) => (
          <span key={stage.title} className="flex flex-none items-center gap-2">
            <span className="guide-chip whitespace-nowrap">
              <span className="workbench-muted mr-1.5 font-mono">{index + 1}</span>
              {stage.short}
            </span>
            {index < STAGES.length - 1 ? <span className="workbench-green">→</span> : null}
          </span>
        ))}
      </div>

      <ol className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {STAGES.map((stage, index) => (
          <li key={stage.title} className="workbench-card flex gap-4 p-5">
            <span className="guide-step-badge" aria-hidden="true">
              {String(index + 1).padStart(2, "0")}
            </span>
            <div>
              <h3 className="workbench-foreground text-base font-bold tracking-[-0.01em]">
                <span className="sr-only">Step {index + 1}: </span>
                {stage.title}
              </h3>
              <p className="workbench-muted mt-2 text-sm leading-6">{stage.text}</p>
            </div>
          </li>
        ))}
      </ol>

      <div className="workbench-surface mt-4 p-5">
        <h3 className="workbench-foreground text-base font-bold">{ORTHOLOG_TITLE}</h3>
        <p className="workbench-muted mt-2 text-sm leading-6">{ORTHOLOG_TEXT}</p>
      </div>
    </section>
  );
}
