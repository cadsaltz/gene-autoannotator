import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import assert from "node:assert/strict";
import nextConfig from "../next.config.mjs";
import { CONTENT_SECURITY_POLICY, securityHeaders } from "./securityHeaders.js";

const frontendDir = path.resolve(import.meta.dirname, "..");

function headerMap(headers) {
  return Object.fromEntries(headers.map(({ key, value }) => [key, value]));
}

test("baseline security headers are always sent", () => {
  for (const production of [true, false]) {
    const headers = headerMap(securityHeaders({ production }));
    assert.equal(headers["X-Content-Type-Options"], "nosniff");
    assert.equal(headers["X-Frame-Options"], "DENY");
    assert.equal(headers["Referrer-Policy"], "strict-origin-when-cross-origin");
    assert.equal(headers["Permissions-Policy"], "camera=(), microphone=(), geolocation=()");
  }
});

test("content security policy is production-only", () => {
  assert.equal(headerMap(securityHeaders({ production: true }))["Content-Security-Policy"], CONTENT_SECURITY_POLICY);
  assert.equal("Content-Security-Policy" in headerMap(securityHeaders({ production: false })), false);
});

test("content security policy keeps browser traffic same-origin", () => {
  const directives = Object.fromEntries(
    CONTENT_SECURITY_POLICY.split(";").map((part) => {
      const [name, ...values] = part.trim().split(/\s+/);
      return [name, values.join(" ")];
    }),
  );
  assert.deepEqual(directives, {
    "default-src": "'self'",
    "img-src": "'self' data:",
    "style-src": "'self' 'unsafe-inline'",
    "script-src": "'self' 'unsafe-inline'",
    "connect-src": "'self'",
    "frame-ancestors": "'none'",
    "base-uri": "'self'",
    "form-action": "'self'",
    "object-src": "'none'",
  });
});

test("next config applies the headers to every route and builds standalone", async () => {
  assert.equal(nextConfig.output, "standalone");
  assert.ok(nextConfig.allowedDevOrigins.length > 0);
  const rules = await nextConfig.headers();
  const catchAll = rules.find((rule) => rule.source === "/:path*");
  assert.ok(catchAll, "expected a /:path* header rule");
  const expected = securityHeaders({ production: process.env.NODE_ENV === "production" });
  assert.deepEqual(catchAll.headers, expected);
});

test("robots.txt allows public pages and hides app routes", async () => {
  const robots = await readFile(path.join(frontendDir, "public", "robots.txt"), "utf8");
  const lines = robots.split("\n").map((line) => line.trim());
  assert.ok(lines.includes("User-agent: *"));
  for (const allowed of ["/", "/legal/"]) {
    assert.ok(lines.includes(`Allow: ${allowed}`), `missing Allow: ${allowed}`);
  }
  for (const hidden of ["/jobs", "/profiles", "/annotations", "/fleet", "/admin", "/api/", "/auth/"]) {
    assert.ok(lines.includes(`Disallow: ${hidden}`), `missing Disallow: ${hidden}`);
  }
});
