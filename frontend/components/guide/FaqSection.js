import Link from "next/link";

import { CONTACT_PLACEHOLDER } from "../../lib/legal";

const KICKER = "FAQ";
const TITLE = "Frequently asked questions";

const FAQ_ITEMS = [
  {
    question: "Why do I sign in with an email code instead of a password?",
    answer:
      "Accounts are passwordless. Each time you sign in we email a 6-digit code that expires after 10 minutes. There is no password for you to reuse or for us to store, so there is no password to leak.",
  },
  {
    question: "Why are there quotas?",
    answer:
      "Annotation runs on shared HPC capacity: every gene means many language-model calls on GPUs that are shared with other work. Quotas keep the queue fair so one account cannot fill it.",
  },
  {
    question: "How long are my jobs and results kept?",
    answer: "Retention periods for accounts, jobs, logs, and backups are described in the Privacy Policy.",
    link: { href: "/legal/privacy", label: "Read the Privacy Policy" },
  },
  {
    question: "How do I delete my account?",
    answer: `The Privacy Policy describes your rights to access, correct, and delete your data. To request deletion, contact the operator at ${CONTACT_PLACEHOLDER}.`,
    link: { href: "/legal/privacy", label: "Read the Privacy Policy" },
  },
  {
    question: "Can I choose which models are used?",
    answer:
      "No. The model mode is configured by the operator on the compute workers and applies to every job. See Tradeoffs and limitations for what each mode means.",
  },
  {
    question: "My job failed. What now?",
    answer:
      "Jobs interrupted by a retryable problem are put back in the queue automatically. If a job still ends up failed, My jobs marks it and you can resubmit it.",
  },
];

export default function FaqSection() {
  return (
    <section id="faq" aria-labelledby="faq-title" className="scroll-mt-6">
      <p className="workbench-kicker">{KICKER}</p>
      <h2 id="faq-title" className="workbench-foreground mt-2 text-3xl font-bold tracking-[-0.04em]">
        {TITLE}
      </h2>

      <div className="mt-6 grid gap-3">
        {FAQ_ITEMS.map((item) => (
          <details key={item.question} className="guide-faq workbench-card group p-0">
            <summary className="workbench-foreground flex cursor-pointer items-center gap-4 rounded-[18px] px-5 py-4 font-bold">
              <h3 className="text-base">{item.question}</h3>
            </summary>
            <div className="workbench-muted px-5 pb-5 text-sm leading-6">
              <p>{item.answer}</p>
              {item.link ? (
                <Link
                  href={item.link.href}
                  className="workbench-green mt-2 inline-block font-bold underline underline-offset-2"
                >
                  {item.link.label}
                </Link>
              ) : null}
            </div>
          </details>
        ))}
      </div>
    </section>
  );
}
