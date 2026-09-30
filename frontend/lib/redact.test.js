import assert from "node:assert/strict";
import test from "node:test";

import { redactConnectionStrings, redactSecretsIn, redactUrlSecrets } from "./redact.js";

test("redactUrlSecrets masks api_key values and keeps neighbouring params", () => {
  assert.equal(
    redactUrlSecrets("https://eutils.ncbi.nlm.nih.gov/esearch.fcgi?db=pmc&api_key=abc123&term=dnaA"),
    "https://eutils.ncbi.nlm.nih.gov/esearch.fcgi?db=pmc&api_key=REDACTED&term=dnaA",
  );
  assert.equal(redactUrlSecrets("API_KEY=Secret1 failed"), "API_KEY=REDACTED failed");
  assert.equal(redactUrlSecrets("q%3Fapi%5Fkey%3Dabc%26db%3Dpmc"), "q%3Fapi%5Fkey%3DREDACTED%26db%3Dpmc");
  assert.equal(redactUrlSecrets("(see ?api_key=abc)"), "(see ?api_key=REDACTED)");
  assert.equal(redactUrlSecrets(""), "");
});

test("redactSecretsIn walks objects and arrays without touching non-strings", () => {
  const input = {
    url: "https://x.test/?api_key=abc",
    nested: [{ source: "api_key=def&x=1" }, 3, null, true],
    "https://y.test/?api_key=ghi": "key",
  };

  assert.deepEqual(redactSecretsIn(input), {
    url: "https://x.test/?api_key=REDACTED",
    nested: [{ source: "api_key=REDACTED&x=1" }, 3, null, true],
    "https://y.test/?api_key=REDACTED": "key",
  });
  assert.equal(input.url, "https://x.test/?api_key=abc");
});

test("redactConnectionStrings hides MongoDB URIs and their credentials", () => {
  assert.equal(
    redactConnectionStrings("failed to connect to mongodb://admin:hunter2@db.internal:27017/app?authSource=admin"),
    "failed to connect to mongodb://[redacted]",
  );
  assert.equal(
    redactConnectionStrings('bad uri "mongodb+srv://u:p@cluster.example.net"'),
    'bad uri "mongodb://[redacted]"',
  );
  assert.equal(redactConnectionStrings("connect ECONNREFUSED"), "connect ECONNREFUSED");
});
