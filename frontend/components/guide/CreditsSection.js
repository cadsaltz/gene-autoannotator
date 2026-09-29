const KICKER = "Data sources and credits";
const TITLE = "Built on public literature and open tools";
const NCBI_NOTE =
  "Literature and gene records come from NCBI (U.S. National Library of Medicine) through the E-utilities API. This service is not endorsed by NCBI.";

const SOURCES = [
  {
    name: "PubMed and PubMed Central (PMC)",
    href: "https://pmc.ncbi.nlm.nih.gov/",
    use: "Paper search, full-text articles, and the PMIDs cited in annotations.",
  },
  {
    name: "NCBI Gene",
    href: "https://www.ncbi.nlm.nih.gov/gene/",
    use: "Gene-name lookup when a name is not supplied.",
  },
  {
    name: "UniProt",
    href: "https://www.uniprot.org/",
    use: "Additional gene-name lookup.",
  },
  {
    name: "KEGG SSDB",
    href: "https://www.kegg.jp/ssdb/",
    use: "Ortholog lookup for the optional ortholog fallback.",
  },
  {
    name: "Gene Ontology",
    href: "https://geneontology.org/",
    use: "The ontology used for GO term resolution.",
  },
  {
    name: "Ollama and open-weight models",
    href: "https://ollama.com/",
    use: "Qwen, Gemma, Mistral, and Llama model families run locally on the compute workers.",
  },
];

const CITATION_HEADING = "How to cite";
const CITATION_TEXT = "If you use these annotations in published work, please cite:";
const CITATION_PLACEHOLDER = "[Paper citation — to be added]";

export default function CreditsSection() {
  return (
    <section id="credits" aria-labelledby="credits-title" className="scroll-mt-6">
      <p className="workbench-kicker">{KICKER}</p>
      <h2 id="credits-title" className="workbench-foreground mt-2 text-3xl font-bold tracking-[-0.04em]">
        {TITLE}
      </h2>
      <p className="workbench-muted mt-3 max-w-2xl leading-7">{NCBI_NOTE}</p>

      <div className="mt-6 grid items-start gap-4 grid-cols-1 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,0.6fr)]">
        <ul className="grid gap-3 sm:grid-cols-2">
          {SOURCES.map((source) => (
            <li key={source.name} className="workbench-card p-5">
              <h3 className="text-base font-bold">
                <a
                  href={source.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="workbench-foreground underline-offset-2 hover:underline"
                >
                  {source.name}
                  <span className="sr-only"> (opens in a new tab)</span>
                </a>
              </h3>
              <p className="workbench-muted mt-1 text-sm leading-6">{source.use}</p>
            </li>
          ))}
        </ul>
        <div className="workbench-card p-5">
          <h3 className="workbench-foreground text-base font-bold">{CITATION_HEADING}</h3>
          <p className="workbench-muted mt-1 text-sm leading-6">{CITATION_TEXT}</p>
          <p className="workbench-muted-bg mt-3 rounded-xl border border-dashed workbench-border p-3 font-mono text-sm text-[#3d463f]">
            {CITATION_PLACEHOLDER}
          </p>
        </div>
      </div>
    </section>
  );
}
