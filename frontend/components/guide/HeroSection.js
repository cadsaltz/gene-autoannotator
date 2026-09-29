import HeroActions from "./HeroActions";

const KICKER = "Gene Autoannotator";
const TITLE = "Literature-backed gene annotations, drafted by AI and cited to PubMed.";
const SUMMARY =
  "Give it a gene from a supported organism and it finds the relevant PubMed Central papers, has several language models extract and cross-check the evidence, and returns a structured, cited annotation for you to review.";
const REVIEW_NOTE = "Generated annotations are curator aids, not curated truth.";

const AT_A_GLANCE = [
  { value: "Up to 20", label: "papers selected per gene, ranked by relevance" },
  { value: "3 models", label: "extract each excerpt independently (default mode)" },
  { value: "PMIDs", label: "cited inline next to the claims they support" },
  { value: "Versions", label: "kept when a gene is annotated again" },
];

export default function HeroSection() {
  return (
    <section id="hero" aria-labelledby="hero-title" className="guide-hero scroll-mt-6 p-6 sm:p-10">
      <p className="workbench-kicker">{KICKER}</p>
      <h1
        id="hero-title"
        className="mt-4 max-w-3xl text-3xl font-bold tracking-[-0.04em] sm:text-5xl"
      >
        {TITLE}
      </h1>
      <p className="guide-hero-muted mt-5 max-w-2xl text-lg leading-8">{SUMMARY}</p>
      <p className="guide-hero-muted mt-3 max-w-2xl text-sm">
        {REVIEW_NOTE}{" "}
        <a href="#disclaimers" className="font-semibold text-[#f5f0e6] underline underline-offset-2">
          Research use only
        </a>
        .
      </p>

      <HeroActions />

      <dl className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {AT_A_GLANCE.map((item) => (
          <div key={item.value} className="guide-hero-stat pt-3">
            <dt className="text-2xl font-bold tracking-[-0.03em]">{item.value}</dt>
            <dd className="guide-hero-muted mt-1 text-sm leading-6">{item.label}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
