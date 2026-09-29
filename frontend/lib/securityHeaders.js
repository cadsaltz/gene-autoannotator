// 'unsafe-inline' scripts: the App Router inlines its flight-data bootstrap
// scripts. connect-src 'self' holds because the browser only calls the Next
// proxy routes (/api/backend, /api/annotations), never the backend origin.
export const CONTENT_SECURITY_POLICY = [
  "default-src 'self'",
  "img-src 'self' data:",
  "style-src 'self' 'unsafe-inline'",
  "script-src 'self' 'unsafe-inline'",
  "connect-src 'self'",
  "frame-ancestors 'none'",
].join("; ");

const BASELINE_HEADERS = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

// `next dev` needs 'unsafe-eval' and a websocket for HMR, so the CSP is
// production-only.
export function securityHeaders({ production }) {
  if (!production) {
    return [...BASELINE_HEADERS];
  }
  return [...BASELINE_HEADERS, { key: "Content-Security-Policy", value: CONTENT_SECURITY_POLICY }];
}
