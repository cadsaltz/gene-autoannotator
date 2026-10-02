import Link from "next/link";

import { CONTACT_PLACEHOLDER, LEGAL_LINKS } from "../lib/legal";

const DATA_SOURCES = [
  { href: "https://www.ncbi.nlm.nih.gov/", label: "NCBI" },
  { href: "https://pubmed.ncbi.nlm.nih.gov/", label: "PubMed" },
  { href: "https://pmc.ncbi.nlm.nih.gov/", label: "PMC" },
];

export default function SiteFooter() {
  return (
    <footer className="border-t border-line bg-surface">
      <div className="text-fg-muted mx-auto flex max-w-7xl flex-col gap-3 px-6 py-6 text-sm">
        <nav aria-label="Legal" className="flex flex-wrap gap-x-2 gap-y-1">
          {LEGAL_LINKS.map((item, index) => (
            <span key={item.href} className="flex gap-2">
              {index > 0 ? <span aria-hidden="true">·</span> : null}
              <Link href={item.href} className="font-semibold text-fg-secondary underline-offset-2 hover:text-fg hover:underline">
                {item.label}
              </Link>
            </span>
          ))}
        </nav>
        <p>
          Data sources: literature and gene records from{" "}
          {DATA_SOURCES.map((source, index) => (
            <span key={source.href}>
              {index > 0 ? (index === DATA_SOURCES.length - 1 ? ", and " : ", ") : null}
              <a
                href={source.href}
                target="_blank"
                rel="noopener noreferrer"
                className="underline underline-offset-2"
              >
                {source.label}
              </a>
            </span>
          ))}{" "}
          (U.S. National Library of Medicine). This service is not endorsed by NCBI.
        </p>
        <p>Contact: {CONTACT_PLACEHOLDER}</p>
      </div>
    </footer>
  );
}
