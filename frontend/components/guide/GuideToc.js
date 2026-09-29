import { GUIDE_SECTIONS } from "./guideSections";

const TOC_HEADING = "On this page";

export default function GuideToc() {
  return (
    <nav
      aria-label="On this page"
      className="workbench-card p-4 lg:sticky lg:top-6 lg:self-start lg:p-5"
    >
      <p className="workbench-kicker">{TOC_HEADING}</p>
      <ol className="mt-3 flex flex-wrap gap-2 lg:flex-col lg:gap-1">
        {GUIDE_SECTIONS.map((section, index) => (
          <li key={section.id}>
            <a
              href={`#${section.id}`}
              className="guide-toc-link flex items-center gap-2 rounded-full px-3 py-1.5 text-sm font-semibold lg:rounded-lg lg:px-2"
            >
              <span aria-hidden="true" className="workbench-muted font-mono text-xs">
                {String(index + 1).padStart(2, "0")}
              </span>
              <span>{section.label}</span>
            </a>
          </li>
        ))}
      </ol>
    </nav>
  );
}
