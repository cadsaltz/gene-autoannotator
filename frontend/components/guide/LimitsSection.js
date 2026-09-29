import QueueLimits from "./QueueLimits";

const KICKER = "Limits and queue";
const TITLE = "One shared queue, fair-use limits per account";
const INTRO =
  "Annotation runs on shared compute, so every submission waits in a single queue and each account has limits.";

const LIMIT_POINTS = [
  {
    title: "Per-account limits",
    text: "Each account has a cap on active jobs (queued plus running), on submissions in the last 24 hours, and on genes per batch. A submission over a limit is rejected with a message saying which limit was hit.",
  },
  {
    title: "Shared queue cap",
    text: "When the whole queue is full, or the operator pauses new submissions, the Jobs page says so and new jobs are refused for a while. Jobs already in the queue keep running.",
  },
  {
    title: "How jobs get picked up",
    text: "Workers claim queued jobs oldest first. On the HPC cluster, a scheduler checks the queue every few minutes and starts at most one GPU allocation at a time, which works through queued jobs and then exits. Other machines can pull jobs from the same queue.",
  },
  {
    title: "How long it takes",
    text: "Jobs can take minutes to hours depending on HPC availability and how much literature a gene has. In our saved example outputs, run times range from about 8 minutes to about 6 hours, not counting time spent waiting in the queue.",
  },
  {
    title: "Progress and retries",
    text: "Progress is reported by phase, not as a time estimate. A job interrupted by a retryable problem, such as a worker going offline, is put back in the queue automatically (up to three attempts in total by default) before it is marked failed.",
  },
];

export default function LimitsSection() {
  return (
    <section id="limits" aria-labelledby="limits-title" className="scroll-mt-6">
      <p className="workbench-kicker">{KICKER}</p>
      <h2 id="limits-title" className="workbench-foreground mt-2 text-3xl font-bold tracking-[-0.04em]">
        {TITLE}
      </h2>
      <p className="workbench-muted mt-3 max-w-2xl leading-7">{INTRO}</p>

      <div className="mt-6 grid items-start gap-4 grid-cols-1 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)]">
        <dl className="workbench-card grid gap-4 p-6">
          {LIMIT_POINTS.map((point) => (
            <div key={point.title} className="border-t workbench-border pt-3 first:border-t-0 first:pt-0">
              <dt className="workbench-foreground font-bold">{point.title}</dt>
              <dd className="workbench-muted mt-1 text-sm leading-6">{point.text}</dd>
            </div>
          ))}
        </dl>
        <QueueLimits />
      </div>
    </section>
  );
}
