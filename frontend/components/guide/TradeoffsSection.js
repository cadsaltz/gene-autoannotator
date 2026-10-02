const KICKER = "Tradeoffs and limitations";
const TITLE = "What the pipeline does well, and where it falls short";
const INTRO =
  "Automated annotation trades some accuracy for speed and breadth. Knowing where it fails helps you decide what to double-check.";

const TRADEOFFS = [
  {
    title: "Language models make mistakes",
    points: [
      "Models can misread a passage, over-generalize, hallucinate details, or attribute a finding to the wrong gene or species.",
      "Consensus across several extractors, traceability checks, and dropping wrong-gene output reduce this risk but do not remove it.",
      "Automated validation checks the shape of the output and the gene identity, not whether the biology is correct.",
    ],
  },
  {
    title: "Only as good as the literature",
    points: [
      "The pipeline reads papers available in PubMed Central (abstract, results, and discussion). Papers outside PubMed Central are not read.",
      "Poorly studied genes get sparse annotations. Unusual article layouts can be parsed incompletely.",
      "Relevance scoring is heuristic, and name-only matches can pull in papers about a same-named gene in another species.",
    ],
  },
  {
    title: "Organisms and profiles",
    points: [
      "Saved organism profiles define the expected locus format, search terms, and relevance rules. The bundled profiles include Mycobacterium tuberculosis H37Rv, several other mycobacteria, Corynebacterium glutamicum, Escherichia coli K-12, Trypanosoma brucei, and two Trypanosoma cruzi strains.",
      "Custom organism/strain submissions are accepted, but validation and retrieval are less tuned than for saved profiles.",
      "Ortholog fallback borrows evidence from a related gene in another organism. It is labeled, but it is indirect evidence.",
    ],
  },
  {
    title: "Speed versus accuracy: model modes",
    points: [
      "The default performance mode uses mid-size open-weight models: qwen3:14b, gemma3:12b, and mistral-nemo:12b as extractors, qwen3:8b for consensus, and gemma3:27b for aggregation.",
      "The lite mode swaps in much smaller models (about 4 GB in total) that run faster on modest hardware but produce lower-quality annotations. A nano mode exists only for infrastructure testing.",
      "The mode is set by the operator on the compute workers, not chosen per job. Reading every excerpt with several models is the main reason jobs are slow.",
    ],
  },
  {
    title: "No guarantee of completeness",
    points: [
      "An empty field means no supported evidence was found, not that the gene lacks that property.",
      "At most 20 papers are analyzed per gene, so relevant work can be missed.",
      "Annotations are drafts for curators to review, not curated truth.",
    ],
  },
];

export default function TradeoffsSection() {
  return (
    <section id="tradeoffs" aria-labelledby="tradeoffs-title" className="scroll-mt-6">
      <p className="workbench-kicker">{KICKER}</p>
      <h2 id="tradeoffs-title" className="workbench-foreground mt-2 text-3xl font-semibold tracking-tight">
        {TITLE}
      </h2>
      <p className="workbench-muted mt-3 max-w-2xl leading-7">{INTRO}</p>

      <div className="mt-6 grid gap-4 md:grid-cols-2">
        {TRADEOFFS.map((item) => (
          <article key={item.title} className="workbench-card p-6 md:last:col-span-2">
            <h3 className="workbench-foreground text-lg font-semibold tracking-tight">{item.title}</h3>
            <ul className="workbench-muted mt-3 grid gap-2 text-sm leading-6">
              {item.points.map((point) => (
                <li key={point} className="flex gap-2">
                  <span aria-hidden="true" className="workbench-amber font-semibold">
                    •
                  </span>
                  <span>{point}</span>
                </li>
              ))}
            </ul>
          </article>
        ))}
      </div>
    </section>
  );
}
