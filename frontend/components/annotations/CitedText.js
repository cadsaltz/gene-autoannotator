import { pubmedUrl, splitCitations } from "../../lib/citations";

export default function CitedText({ text }) {
  return (
    <>
      {splitCitations(text).map((segment, index) =>
        segment.type === "pmid" ? (
          <a
            key={index}
            href={pubmedUrl(segment.value)}
            target="_blank"
            rel="noopener noreferrer"
            className="mx-0.5 whitespace-nowrap rounded-md border border-brand-tint-strong bg-brand-tint px-1.5 py-px font-mono text-[13px] text-brand-fg transition hover:border-brand-line"
          >
            PMID {segment.value}
          </a>
        ) : (
          <span key={index}>{segment.value}</span>
        ),
      )}
    </>
  );
}
