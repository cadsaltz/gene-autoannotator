const KICKER = "What you get";
const TITLE = "A gene-level annotation you can check line by line";
const INTRO =
  "Each finished job produces one structured annotation for your gene, with the evidence trail needed to review it.";

const DELIVERABLES = [
  {
    title: "Structured fields",
    text: "Function, functional category, drug-susceptibility impact, infection impact, and essentiality in vitro and in vivo. Organism profiles can define their own fields.",
  },
  {
    title: "Cited literature",
    text: "PubMed IDs (PMIDs) appear inline next to the statements they support, and the PubMed Central papers that were analyzed are listed with the annotation.",
  },
  {
    title: "GO terms",
    text: "When GO resolution is enabled for the organism profile, the function text is mapped to Gene Ontology terms, each with a confidence score.",
  },
  {
    title: "Review metadata",
    text: "Annotation notes on conflicts and gaps, quality flags, relevance scores, paper counts, and run time, plus earlier versions when a gene is re-run.",
  },
];

const EXAMPLE_CAPTION =
  "Trimmed excerpt of a real completed annotation JSON produced by this pipeline (default field set, GO resolution not part of this run).";

const EXAMPLE_ANNOTATION = {
  gene_id: "TcCLB.503799.4",
  name: "AUK1",
  organism: "Trypanosoma cruzi CL Brener",
  function:
    "involved in mitotic spindle assembling and chromosome segregation; appears to play a role during the initiation of kinetoplast duplication (PMID: 30897087); coordinates events associated with mitosis and cytokinesis; phosphorylates histone H3 (PMID: 19320832); …",
  functional_category: ["Mitosis", "Cell cycle", "Cytokinesis"],
  drug_susc_impact:
    "Growth of cultured bloodstream forms is sensitive to Hesperadin (IC50 of 50 nM) (PMID: 19320832).",
  infection_impact:
    "Essential contribution to infection (demonstrated by conditional knockdown in infected mice) (PMID: 19320832).",
  essential_in_vitro: true,
  essential_in_vivo: true,
  annotation_notes:
    "… the conflicting reports regarding in vitro essentiality (PMID: 34128702 reports false, while PMID: 19320832 reports true) were resolved by prioritizing the experimental evidence from PMID: 19320832. …",
  literature: {
    total_papers_retrieved: 37,
    papers_analyzed: 12,
    sections_analyzed: 22,
    cumulative_relevance: 6.961,
    target_relevance: 9.0,
  },
  quality_flags: [],
  duration_sec: 486.2,
  selected_papers: [
    {
      pmid: "30897087",
      year: 2019,
      score: 0.912,
      title:
        "Aurora kinase protein family in Trypanosoma cruzi: Novel role of an AUK-B homologue in kinetoplast replication",
      warnings: [],
    },
    {
      pmid: "19320832",
      year: 2009,
      score: 0.497,
      title:
        "The cell cycle as a therapeutic target against Trypanosoma brucei: Hesperadin inhibits Aurora kinase-1 and blocks mitotic progression in bloodstream forms",
      warnings: ["name_only_match"],
    },
  ],
};

const EXAMPLE_REVIEW_NOTE =
  "Reviewer's eye: PMID 19320832 studies the Trypanosoma brucei Aurora kinase and was matched by gene name only (flagged name_only_match), yet it backs several fields here. Cross-species evidence like this is exactly what to verify before relying on a field.";

const PMID_PATTERN = /(PMID:?\s*\d+)/g;

function pubmedUrl(pmid) {
  return `https://pubmed.ncbi.nlm.nih.gov/${pmid}/`;
}

function CitedText({ text }) {
  return text.split(PMID_PATTERN).map((part, index) => {
    const match = part.match(/^PMID:?\s*(\d+)$/);
    if (!match) return <span key={index}>{part}</span>;
    return (
      <a
        key={index}
        href={pubmedUrl(match[1])}
        target="_blank"
        rel="noopener noreferrer"
        className="workbench-green font-semibold underline underline-offset-2"
      >
        {part}
      </a>
    );
  });
}

function ExampleField({ label, children }) {
  return (
    <div className="border-t workbench-border pt-3">
      <dt className="workbench-muted text-xs font-bold uppercase tracking-[0.1em]">{label}</dt>
      <dd className="workbench-foreground mt-1 text-sm leading-6">{children}</dd>
    </div>
  );
}

function ExampleCard() {
  const example = EXAMPLE_ANNOTATION;
  const literature = example.literature;
  return (
    <figure className="workbench-surface overflow-hidden">
      <div className="workbench-muted-bg flex flex-wrap items-baseline justify-between gap-2 border-b workbench-border px-5 py-4">
        <div>
          <p className="workbench-kicker">Example output</p>
          <p className="workbench-foreground mt-1 text-xl font-bold tracking-[-0.02em]">
            {example.name}{" "}
            <span className="workbench-muted font-mono text-sm font-semibold">{example.gene_id}</span>
          </p>
          <p className="workbench-muted text-sm italic">{example.organism}</p>
        </div>
        <span className="guide-chip guide-chip-green">All six fields supported</span>
      </div>

      <dl className="grid gap-3 px-5 py-4">
        <ExampleField label="Function">
          <CitedText text={example.function} />
        </ExampleField>
        <ExampleField label="Functional category">
          <span className="flex flex-wrap gap-1.5">
            {example.functional_category.map((category) => (
              <span key={category} className="guide-chip">
                {category}
              </span>
            ))}
          </span>
        </ExampleField>
        <ExampleField label="Drug susceptibility impact">
          <CitedText text={example.drug_susc_impact} />
        </ExampleField>
        <ExampleField label="Infection impact">
          <CitedText text={example.infection_impact} />
        </ExampleField>
        <div className="grid grid-cols-2 gap-3">
          <ExampleField label="Essential in vitro">{example.essential_in_vitro ? "True" : "False"}</ExampleField>
          <ExampleField label="Essential in vivo">{example.essential_in_vivo ? "True" : "False"}</ExampleField>
        </div>
        <ExampleField label="Annotation notes">
          <CitedText text={example.annotation_notes} />
        </ExampleField>
      </dl>

      <div className="workbench-muted-bg border-t workbench-border px-5 py-4">
        <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          <div>
            <dt className="workbench-muted text-xs font-bold uppercase tracking-[0.1em]">Papers</dt>
            <dd className="workbench-foreground mt-1 font-semibold">
              {literature.papers_analyzed} of {literature.total_papers_retrieved}
            </dd>
          </div>
          <div>
            <dt className="workbench-muted text-xs font-bold uppercase tracking-[0.1em]">Sections</dt>
            <dd className="workbench-foreground mt-1 font-semibold">{literature.sections_analyzed}</dd>
          </div>
          <div>
            <dt className="workbench-muted text-xs font-bold uppercase tracking-[0.1em]">Relevance</dt>
            <dd className="workbench-foreground mt-1 font-semibold">
              {literature.cumulative_relevance} / {literature.target_relevance.toFixed(1)}
            </dd>
          </div>
          <div>
            <dt className="workbench-muted text-xs font-bold uppercase tracking-[0.1em]">Run time</dt>
            <dd className="workbench-foreground mt-1 font-semibold">
              {Math.round(example.duration_sec / 60)} min
            </dd>
          </div>
        </dl>

        <p className="workbench-muted mt-4 text-xs font-bold uppercase tracking-[0.1em]">
          Selected papers (2 of {literature.papers_analyzed} shown)
        </p>
        <ul className="mt-2 grid gap-2">
          {example.selected_papers.map((paper) => (
            <li key={paper.pmid} className="workbench-surface px-3 py-2 text-sm">
              <a
                href={pubmedUrl(paper.pmid)}
                target="_blank"
                rel="noopener noreferrer"
                className="workbench-foreground font-semibold underline-offset-2 hover:underline"
              >
                {paper.title}
              </a>
              <span className="workbench-muted mt-1 flex flex-wrap items-center gap-2 text-xs">
                <span>
                  PMID {paper.pmid} · {paper.year} · relevance {paper.score}
                </span>
                {paper.warnings.map((warning) => (
                  <span key={warning} className="guide-chip guide-chip-amber font-mono">
                    {warning}
                  </span>
                ))}
              </span>
            </li>
          ))}
        </ul>
        <p className="mt-4 rounded-xl border workbench-border bg-[#fffefa] p-3 text-sm leading-6 text-[#5f4b2e]">
          {EXAMPLE_REVIEW_NOTE}
        </p>
      </div>
      <figcaption className="workbench-muted border-t workbench-border px-5 py-3 text-xs leading-5">
        {EXAMPLE_CAPTION}
      </figcaption>
    </figure>
  );
}

export default function WhatYouGetSection() {
  return (
    <section id="what-you-get" aria-labelledby="what-you-get-title" className="scroll-mt-6">
      <p className="workbench-kicker">{KICKER}</p>
      <h2
        id="what-you-get-title"
        className="workbench-foreground mt-2 text-3xl font-bold tracking-[-0.04em]"
      >
        {TITLE}
      </h2>
      <p className="workbench-muted mt-3 max-w-2xl leading-7">{INTRO}</p>

      <div className="mt-6 grid items-start gap-6 grid-cols-1 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
          {DELIVERABLES.map((item) => (
            <li key={item.title} className="workbench-card p-5">
              <h3 className="workbench-foreground text-lg font-bold tracking-[-0.02em]">{item.title}</h3>
              <p className="workbench-muted mt-2 text-sm leading-6">{item.text}</p>
            </li>
          ))}
        </ul>
        <ExampleCard />
      </div>
    </section>
  );
}
