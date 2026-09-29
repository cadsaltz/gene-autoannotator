export default function LegalPlaceholder({ title, sections, draft }) {
  return (
    <article className="mx-auto grid max-w-3xl gap-6">
      <div
        className="workbench-amber-bg rounded-xl border workbench-border p-4 text-sm font-semibold text-[#5f4b2e]"
        role="note"
      >
        DRAFT — pending legal review. This page lists what the final text must
        cover; it is not the final policy.
      </div>

      <header>
        <p className="workbench-kicker">Legal</p>
        <h1 className="workbench-foreground mt-2 text-4xl font-bold tracking-[-0.04em]">
          {title}
        </h1>
      </header>

      {draft && draft.length > 0 ? (
        <section className="workbench-card p-6">
          <h2 className="workbench-foreground text-xl font-bold tracking-[-0.02em]">
            Draft wording
          </h2>
          <div className="workbench-muted mt-3 grid gap-3 text-sm leading-6">
            {draft.map((paragraph) => (
              <p key={paragraph}>{paragraph}</p>
            ))}
          </div>
        </section>
      ) : null}

      {sections.map((section) => (
        <section key={section.heading} className="workbench-card p-6">
          <h2 className="workbench-foreground text-xl font-bold tracking-[-0.02em]">
            {section.heading}
          </h2>
          <p className="workbench-kicker mt-4">Must include</p>
          <ul className="workbench-muted mt-2 grid gap-1 text-sm leading-6">
            {section.mustInclude.map((item) => (
              <li key={item} className="flex gap-2">
                <span aria-hidden="true">☐</span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </article>
  );
}
