// Keep in sync with the backend TERMS_VERSION default (backend/api.py).
export const TERMS_VERSION = "draft-2026-09";

export const CONTACT_PLACEHOLDER = "[contact email]";

export const RESEARCH_DISCLAIMER =
  "Research use only. AI-generated annotations can be incomplete or wrong. Verify against primary sources before relying on them.";

export const LEGAL_LINKS = [
  { href: "/legal/terms", label: "Terms" },
  { href: "/legal/privacy", label: "Privacy" },
  { href: "/legal/acceptable-use", label: "Acceptable Use" },
  { href: "/legal/disclaimer", label: "Disclaimer" },
];

export const LEGAL_DOCUMENTS = {
  terms: {
    title: "Terms of Service",
    sections: [
      {
        heading: "Operating entity and contact",
        mustInclude: ["Operating entity: [Operating entity]", `Contact: ${CONTACT_PLACEHOLDER}`],
      },
      {
        heading: "Eligibility",
        mustInclude: ["Who may use the service (e.g. research/academic use)", "Minimum age"],
      },
      {
        heading: "Account rules",
        mustInclude: ["One person per account", "Accurate email address"],
      },
      {
        heading: "Service provided \"as is\"",
        mustInclude: ["Service provided \"as is\"", "No uptime guarantee"],
      },
      {
        heading: "Quotas and fair use",
        mustInclude: ["Quotas and fair use"],
      },
      {
        heading: "User responsibilities",
        mustInclude: ["User responsibilities for submitted data"],
      },
      {
        heading: "Intellectual property",
        mustInclude: [
          "Who owns generated annotations",
          "License for users to use outputs",
          "Third-party literature rights",
        ],
      },
      {
        heading: "Termination and suspension",
        mustInclude: ["Termination/suspension rights"],
      },
      {
        heading: "Limitation of liability",
        mustInclude: ["Limitation of liability"],
      },
      {
        heading: "Indemnification",
        mustInclude: ["Indemnification"],
      },
      {
        heading: "Governing law",
        mustInclude: ["Governing law/jurisdiction"],
      },
      {
        heading: "Changes to terms",
        mustInclude: ["Changes to terms and notice"],
      },
      {
        heading: "Effective date and version",
        mustInclude: ["Effective date/version", `Current version: ${TERMS_VERSION}`],
      },
    ],
  },
  privacy: {
    title: "Privacy Policy",
    sections: [
      {
        heading: "What is collected",
        mustInclude: [
          "Email",
          "Optional username",
          "IP addresses",
          "Session cookie",
          "Submitted gene/locus queries",
          "Job history",
          "Audit logs",
        ],
      },
      {
        heading: "Why it is collected",
        mustInclude: ["Authentication", "Abuse prevention", "Running jobs"],
      },
      {
        heading: "Legal basis",
        mustInclude: ["Legal basis if GDPR applies"],
      },
      {
        heading: "Processors",
        mustInclude: [
          "MongoDB Atlas",
          "Resend",
          "Hosting provider",
          "Cloudflare if used",
          "HPC/institution",
        ],
      },
      {
        heading: "Retention periods",
        mustInclude: ["Accounts", "Jobs", "Logs", "Backups"],
      },
      {
        heading: "Cookies",
        mustInclude: ["Single ga_session HttpOnly cookie, 90-day sliding"],
      },
      {
        heading: "User rights",
        mustInclude: ["Access, deletion, and correction", "How to request"],
      },
      {
        heading: "Security",
        mustInclude: ["Security measures summary"],
      },
      {
        heading: "Children's data",
        mustInclude: ["Children's data"],
      },
      {
        heading: "International transfers",
        mustInclude: ["International transfers"],
      },
      {
        heading: "Contact",
        mustInclude: [`Contact: ${CONTACT_PLACEHOLDER}`],
      },
      {
        heading: "Effective date",
        mustInclude: ["Effective date"],
      },
    ],
  },
  "acceptable-use": {
    title: "Acceptable Use Policy",
    sections: [
      {
        heading: "Automated use",
        mustInclude: ["No automated scraping or bulk submission outside quotas"],
      },
      {
        heading: "Accounts and quotas",
        mustInclude: ["No account sharing or evading quotas/bans"],
      },
      {
        heading: "Other users and admin functions",
        mustInclude: ["No attempts to access other users' data or admin functions"],
      },
      {
        heading: "Attacks on the service",
        mustInclude: ["No attacks on the service (DoS, probing)"],
      },
      {
        heading: "Unlawful or harmful use",
        mustInclude: ["No unlawful or harmful use"],
      },
      {
        heading: "Sensitive data",
        mustInclude: ["No submitting sensitive personal data"],
      },
      {
        heading: "Consequences",
        mustInclude: ["Suspension", "Ban"],
      },
      {
        heading: "Reporting abuse",
        mustInclude: [`Reporting abuse contact: ${CONTACT_PLACEHOLDER}`],
      },
    ],
  },
  disclaimer: {
    title: "Disclaimer",
    draft: [
      "Gene Autoannotator is a research tool. Annotations on this site are generated automatically by AI from published literature and may be inaccurate, incomplete, or out of date.",
      "[Operating entity] is not responsible for inaccurate information in generated annotations or for any decisions made based on them. Use the service and its outputs at your own risk.",
      "Nothing on this site is medical, clinical, or diagnostic advice. Always verify annotations against the primary sources before relying on them.",
    ],
    sections: [
      {
        heading: "Research use only",
        mustInclude: ["Research use only"],
      },
      {
        heading: "Not medical advice",
        mustInclude: ["Not medical/clinical/diagnostic advice"],
      },
      {
        heading: "AI-generated content",
        mustInclude: ["AI-generated content may be inaccurate, incomplete, or outdated"],
      },
      {
        heading: "Literature coverage",
        mustInclude: ["Outputs depend on available literature"],
      },
      {
        heading: "No warranty",
        mustInclude: ["No warranty"],
      },
      {
        heading: "Verification",
        mustInclude: ["Users verify against primary sources"],
      },
      {
        heading: "Responsibility for decisions",
        mustInclude: ["Not responsible for decisions made from outputs"],
      },
      {
        heading: "Citation",
        mustInclude: ["Citation guidance"],
      },
    ],
  },
};
