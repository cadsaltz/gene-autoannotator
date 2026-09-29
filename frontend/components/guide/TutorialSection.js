import Link from "next/link";

const KICKER = "How to use it";
const TITLE = "Your first annotation, step by step";
const INTRO = "No installation needed. Everything below happens in the browser.";

const STEPS = [
  {
    title: "Create an account with an email code",
    link: { href: "/signup", label: "Open sign-up" },
    points: [
      "Enter your email (a username is optional) and accept the Terms and Acceptable Use Policy.",
      "We email you a 6-digit code. Enter it on the verification screen; codes expire after 10 minutes.",
      "Next time, use Sign in with the same email to get a fresh code.",
    ],
  },
  {
    title: "Submit a gene or a small batch",
    link: { href: "/jobs", label: "Open Jobs" },
    points: [
      "Choose an organism profile. The form shows the locus format that profile expects, for example Rv0001 or TcCLB.503799.4.",
      "Enter a locus, a gene name, or both. Giving both improves validation and paper retrieval.",
      "For several genes, switch to Batch: paste one identifier per line (or locus,name pairs), or upload a .txt, .csv, or .tsv file. Select Validate batch, pick a locus for any ambiguous rows, then queue it.",
    ],
  },
  {
    title: "Watch “My jobs”",
    points: [
      "Queued jobs show their place in line. Running jobs show the current phase, such as Fetching papers, Extracting sections, or Aggregating results.",
      "The list refreshes on its own every 15 seconds, so you can leave and come back.",
      "You can cancel a job while it is queued or running. Failed jobs can be resubmitted.",
    ],
  },
  {
    title: "Open the finished annotation",
    points: [
      "When a job completes, select View annotation next to it to open the Annotations page.",
      "You'll see the generated fields, any GO terms, an Annotation metadata panel, the PMC IDs analyzed, version history, and the raw JSON.",
    ],
  },
  {
    title: "Read the evidence and confidence signals",
    points: [
      "PMID citations sit inline next to claims. Open them on PubMed and check that the paper says what the annotation claims.",
      "“No supported data” means the pipeline found no supported evidence for that field. It is not a negative result.",
      "Quality flags summarize the literature base, with values such as strong_literature_support, weak_literature_support, limited_literature, or relied_on_low_relevance_papers.",
      "Cumulative relevance is compared with the 9.0 target. Annotation notes explain conflicts between papers and which fields stayed unknown.",
      "Fields borrowed from an ortholog are labeled as such, and each GO term carries a confidence score in the raw JSON.",
    ],
  },
];

export default function TutorialSection() {
  return (
    <section id="tutorial" aria-labelledby="tutorial-title" className="scroll-mt-6">
      <p className="workbench-kicker">{KICKER}</p>
      <h2 id="tutorial-title" className="workbench-foreground mt-2 text-3xl font-bold tracking-[-0.04em]">
        {TITLE}
      </h2>
      <p className="workbench-muted mt-3 max-w-2xl leading-7">{INTRO}</p>

      <ol className="mt-6 grid gap-4">
        {STEPS.map((step, index) => (
          <li key={step.title} className="workbench-card grid gap-4 p-5 sm:grid-cols-[auto_minmax(0,1fr)] sm:p-6">
            <span className="guide-step-badge" aria-hidden="true">
              {index + 1}
            </span>
            <div>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h3 className="workbench-foreground text-lg font-bold tracking-[-0.02em]">
                  <span className="sr-only">Step {index + 1}: </span>
                  {step.title}
                </h3>
                {step.link ? (
                  <Link href={step.link.href} className="workbench-button workbench-button-secondary">
                    {step.link.label}
                  </Link>
                ) : null}
              </div>
              <ul className="workbench-muted mt-3 grid gap-2 text-sm leading-6">
                {step.points.map((point) => (
                  <li key={point} className="flex gap-2">
                    <span aria-hidden="true" className="workbench-green font-bold">
                      ›
                    </span>
                    <span>{point}</span>
                  </li>
                ))}
              </ul>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
