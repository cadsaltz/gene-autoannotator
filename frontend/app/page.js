import Link from "next/link";

import AppShell from "../components/AppShell";

export default function Home() {
  return (
    <AppShell publicPage>
      <section className="grid gap-6 lg:grid-cols-[1.15fr_0.85fr] lg:items-start">
        <div className="workbench-card p-7">
          <p className="workbench-kicker">
            README for the web app
          </p>
          <h1 className="workbench-foreground mt-3 max-w-4xl text-4xl font-bold tracking-[-0.04em] sm:text-5xl">
            Generate literature-backed gene annotations.
          </h1>
          <p className="workbench-muted mt-5 text-lg leading-8">
            The autoannotator takes a saved profile or custom organism plus a
            gene name, locus, or both, gathers relevant literature, asks the
            configured model to synthesize an annotation, and stores the
            generated result for review. Runs can take a long time, so the web
            app submits work to a backend queue and lets you come back later.
          </p>

          <div className="mt-8 flex flex-wrap gap-3">
            <Link
              href="/jobs"
              className="workbench-button workbench-button-primary"
            >
              Submit a job
            </Link>
            <Link
              href="/annotations"
              className="workbench-button workbench-button-secondary"
            >
              Search annotations
            </Link>
          </div>
        </div>

        <aside className="workbench-amber-bg workbench-foreground rounded-[18px] border workbench-border p-6">
          <h2 className="text-xl font-bold tracking-[-0.02em]">Important limitations</h2>
          <ul className="mt-4 space-y-3 text-sm leading-6 text-[#5f4b2e]">
            <li>Only one annotation job runs at a time; new jobs wait in order.</li>
            <li>Real jobs require the same Ollama, model, PubMed, and cache setup as the CLI.</li>
            <li>Generated annotations should be reviewed before being treated as curated truth.</li>
            <li>Progress is intentionally coarse until the annotator pipeline is instrumented in more detail.</li>
          </ul>
        </aside>
      </section>

      <section className="mt-6 grid gap-4 lg:grid-cols-3">
        <div className="workbench-card p-6">
          <h2 className="workbench-foreground text-xl font-bold tracking-[-0.02em]">Inputs</h2>
          <p className="workbench-muted mt-3 text-sm leading-6">
            Jobs need a profile or organism plus either a gene name or locus.
            Profiles improve validation and retrieval, but custom organisms can
            still be submitted.
          </p>
        </div>

        <div className="workbench-card p-6">
          <h2 className="workbench-foreground text-xl font-bold tracking-[-0.02em]">Queue</h2>
          <p className="workbench-muted mt-3 text-sm leading-6">
            Submissions are persisted in SQLite. The worker drains queued jobs
            sequentially so heavy annotation runs do not compete with each other.
          </p>
        </div>

        <div className="workbench-card p-6">
          <h2 className="workbench-foreground text-xl font-bold tracking-[-0.02em]">Results</h2>
          <p className="workbench-muted mt-3 text-sm leading-6">
            Completed jobs are saved to MongoDB by profile/locus or profile/name
            for name-only submissions. New runs preserve older versions.
          </p>
        </div>
      </section>
    </AppShell>
  );
}
