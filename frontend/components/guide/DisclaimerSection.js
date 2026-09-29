import Link from "next/link";

const KICKER = "Disclaimers";
const TITLE = "Research use only";
const DISCLAIMER_POINTS = [
  {
    lead: "Research use only.",
    text: "Nothing on this site is medical, clinical, or diagnostic advice.",
  },
  {
    lead: "AI-generated annotations can be incomplete or wrong.",
    text: "They are produced automatically from published literature and may be inaccurate or out of date.",
  },
  {
    lead: "No responsibility for generated content.",
    text: "[Operating entity] is not responsible for inaccurate information in generated annotations or for any decisions made based on them.",
  },
  {
    lead: "Use at your own risk.",
    text: "You use the service and its outputs at your own risk. Always verify annotations against the primary sources before relying on them.",
  },
];
const FULL_TEXT_LINK = "Read the full Disclaimer";

export default function DisclaimerSection() {
  return (
    <section id="disclaimers" aria-labelledby="disclaimers-title" className="scroll-mt-6">
      <div className="workbench-amber-bg rounded-[18px] border workbench-border-amber p-6 sm:p-8">
        <p className="workbench-kicker guide-kicker-amber">{KICKER}</p>
        <h2 id="disclaimers-title" className="workbench-foreground mt-2 text-3xl font-bold tracking-[-0.04em]">
          {TITLE}
        </h2>
        <ul className="mt-5 grid gap-3 text-sm leading-6 text-[#5f4b2e] sm:grid-cols-2">
          {DISCLAIMER_POINTS.map((point) => (
            <li key={point.lead} className="rounded-xl border border-[#e3cfa9] bg-[#fffaf0] p-4">
              <strong className="workbench-foreground block font-bold">{point.lead}</strong>
              {point.text}
            </li>
          ))}
        </ul>
        <Link
          href="/legal/disclaimer"
          className="workbench-button workbench-button-primary mt-6 min-h-11 px-5 text-sm"
        >
          {FULL_TEXT_LINK}
        </Link>
      </div>
    </section>
  );
}
