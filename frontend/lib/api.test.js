import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import {
  createBatch,
  createProfile,
  deleteProfile,
  generateRegexFromDescription,
  generateRegexFromExamples,
  getAnnotationApiBaseUrl,
  getApiBaseUrl,
  getBatch,
  getProfile,
  updateProfile,
  validateBatch,
  validateJob,
} from "./api.js";

const originalFetch = globalThis.fetch;
const originalBackendApiBaseUrl = process.env.BACKEND_API_BASE_URL;

afterEach(() => {
  if (originalFetch === undefined) {
    delete globalThis.fetch;
  } else {
    globalThis.fetch = originalFetch;
  }
  if (originalBackendApiBaseUrl === undefined) {
    delete process.env.BACKEND_API_BASE_URL;
  } else {
    process.env.BACKEND_API_BASE_URL = originalBackendApiBaseUrl;
  }
});

function mockFetch(handler) {
  globalThis.fetch = async (url, options = {}) => {
    const result = handler(url, options);
    return {
      ok: true,
      json: async () => result ?? {},
    };
  };
}

function mockErrorFetch(payload, status = 422) {
  globalThis.fetch = async () => ({
    ok: false,
    status,
    json: async () => payload,
  });
}

test("profile helpers call encoded profile endpoints", async () => {
  process.env.BACKEND_API_BASE_URL = "http://backend.test";
  const calls = [];
  mockFetch((url, options) => {
    calls.push({ url, options });
  });

  await getProfile("custom/profile 1");
  await createProfile({ profile_id: "new-profile" });
  await updateProfile("custom/profile 1", { canonical_name: "Custom" });
  await deleteProfile("custom/profile 1");

  assert.deepEqual(
    calls.map((call) => [call.url, call.options.method, call.options.body]),
    [
      ["http://backend.test/profiles/custom%2Fprofile%201", undefined, undefined],
      ["http://backend.test/profiles", "POST", JSON.stringify({ profile_id: "new-profile" })],
      [
        "http://backend.test/profiles/custom%2Fprofile%201",
        "PUT",
        JSON.stringify({ canonical_name: "Custom" }),
      ],
      ["http://backend.test/profiles/custom%2Fprofile%201", "DELETE", undefined],
    ],
  );
});

test("regex helpers post to the generation endpoints", async () => {
  process.env.BACKEND_API_BASE_URL = "http://backend.test";
  const calls = [];
  mockFetch((url, options) => {
    calls.push({ url, options });
    return { regex: "^Rv\\d{4}[Ac]?$" };
  });

  await generateRegexFromExamples({ examples: ["Rv1000"] });
  await generateRegexFromDescription({ description: "Rv then 4 digits" });

  assert.deepEqual(
    calls.map((call) => [call.url, call.options.method, call.options.body]),
    [
      [
        "http://backend.test/regex/from-examples",
        "POST",
        JSON.stringify({ examples: ["Rv1000"] }),
      ],
      [
        "http://backend.test/regex/from-description",
        "POST",
        JSON.stringify({ description: "Rv then 4 digits" }),
      ],
    ],
  );
});

test("batch helpers call encoded batch endpoints", async () => {
  process.env.BACKEND_API_BASE_URL = "http://backend.test";
  const calls = [];
  mockFetch((url, options) => {
    calls.push({ url, options });
    return { batch_id: "batch/2026-001" };
  });

  const payload = {
    profile: "mtb-h37rv",
    targets: [{ locus: "Rv0001", name: "dnaA" }],
  };

  await validateBatch(payload);
  await createBatch(payload);
  await getBatch("batch/2026-001");

  assert.deepEqual(
    calls.map((call) => [call.url, call.options.method, call.options.body]),
    [
      ["http://backend.test/batches/validate", "POST", JSON.stringify(payload)],
      ["http://backend.test/batches", "POST", JSON.stringify(payload)],
      ["http://backend.test/batches/batch%2F2026-001", undefined, undefined],
    ],
  );
});

test("validateJob forwards the complete flexible target payload", async () => {
  process.env.BACKEND_API_BASE_URL = "http://backend.test";
  const payload = {
    profile: "",
    organism: "Trypanosoma cruzi",
    strain: "CL Brener",
    locus: "TcCLB.503799.4",
    name: "calmodulin",
    locus_regex: "^TcCLB",
    search_terms: ["T. cruzi"],
    target_patterns: ["Trypanosoma cruzi"],
    off_target_patterns: ["Trypanosoma"],
    excluded_species_patterns: ["Trypanosoma brucei"],
  };
  let received;
  mockFetch((url, options) => {
    received = { url, options };
    return { valid: true };
  });

  await validateJob(payload);

  assert.equal(received.url, "http://backend.test/validate");
  assert.equal(received.options.method, "POST");
  assert.deepEqual(JSON.parse(received.options.body), payload);
});

test("api helpers render FastAPI validation detail arrays as readable error messages", async () => {
  process.env.BACKEND_API_BASE_URL = "http://backend.test";
  mockErrorFetch({ detail: [{ msg: "name or locus is required" }] });

  await assert.rejects(
    () => getProfile("mtb-h37rv"),
    /name or locus is required/,
  );
});

function withBrowserLocation(location, callback) {
  const originalWindow = globalThis.window;
  globalThis.window = { location };
  try {
    callback();
  } finally {
    if (originalWindow === undefined) {
      delete globalThis.window;
    } else {
      globalThis.window = originalWindow;
    }
  }
}

function withApiBaseUrl(value, callback) {
  const originalValue = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (value === undefined) {
    delete process.env.NEXT_PUBLIC_API_BASE_URL;
  } else {
    process.env.NEXT_PUBLIC_API_BASE_URL = value;
  }

  try {
    callback();
  } finally {
    if (originalValue === undefined) {
      delete process.env.NEXT_PUBLIC_API_BASE_URL;
    } else {
      process.env.NEXT_PUBLIC_API_BASE_URL = originalValue;
    }
  }
}

function withBackendApiBaseUrl(value, callback) {
  const originalValue = process.env.BACKEND_API_BASE_URL;
  if (value === undefined) {
    delete process.env.BACKEND_API_BASE_URL;
  } else {
    process.env.BACKEND_API_BASE_URL = value;
  }

  try {
    callback();
  } finally {
    if (originalValue === undefined) {
      delete process.env.BACKEND_API_BASE_URL;
    } else {
      process.env.BACKEND_API_BASE_URL = originalValue;
    }
  }
}

function withoutBrowser(callback) {
  const originalWindow = globalThis.window;
  delete globalThis.window;
  try {
    callback();
  } finally {
    if (originalWindow !== undefined) {
      globalThis.window = originalWindow;
    }
  }
}

test("getApiBaseUrl uses the same-origin backend proxy in the browser", () => {
  withApiBaseUrl(undefined, () => {
    withBrowserLocation({ protocol: "http:", hostname: "10.1.2.3" }, () => {
      assert.equal(getApiBaseUrl(), "/api/backend");
    });
  });
});

test("getApiBaseUrl ignores public API URLs on the server", () => {
  withApiBaseUrl("http://10.158.45.197:8000", () => {
    withBackendApiBaseUrl(undefined, () => {
      withoutBrowser(() => {
        assert.equal(getApiBaseUrl(), "http://127.0.0.1:8000");
      });
    });
  });
});

test("getApiBaseUrl uses the private backend API URL on the server", () => {
  withApiBaseUrl("http://10.158.45.197:8000", () => {
    withBackendApiBaseUrl("http://backend.internal:8000", () => {
      withoutBrowser(() => {
        assert.equal(getApiBaseUrl(), "http://backend.internal:8000");
      });
    });
  });
});

test("getApiBaseUrl prefers COORDINATOR_API_BASE_URL over BACKEND_API_BASE_URL on the server", () => {
  const originalCoord = process.env.COORDINATOR_API_BASE_URL;
  const originalBackend = process.env.BACKEND_API_BASE_URL;
  try {
    process.env.COORDINATOR_API_BASE_URL = "http://coordinator.test";
    process.env.BACKEND_API_BASE_URL = "http://backend.test";
    assert.equal(getApiBaseUrl(), "http://coordinator.test");
  } finally {
    if (originalCoord === undefined) delete process.env.COORDINATOR_API_BASE_URL;
    else process.env.COORDINATOR_API_BASE_URL = originalCoord;
    if (originalBackend === undefined) delete process.env.BACKEND_API_BASE_URL;
    else process.env.BACKEND_API_BASE_URL = originalBackend;
  }
});

test("getApiBaseUrl ignores a loopback API URL in the browser", () => {
  withApiBaseUrl("http://localhost:8000", () => {
    withBrowserLocation({ protocol: "http:", hostname: "10.1.2.3" }, () => {
      assert.equal(getApiBaseUrl(), "/api/backend");
    });
  });
});

test("getApiBaseUrl ignores a stale network API URL in the browser", () => {
  withApiBaseUrl("http://10.158.45.197:8000", () => {
    withBrowserLocation({ protocol: "http:", hostname: "10.19.178.136" }, () => {
      assert.equal(getApiBaseUrl(), "/api/backend");
    });
  });
});

test("getAnnotationApiBaseUrl uses the dedicated Next annotation API in the browser", () => {
  withBrowserLocation({ protocol: "http:", hostname: "10.1.2.3" }, () => {
    assert.equal(getAnnotationApiBaseUrl(), "/api/annotations");
  });
});

test("getAnnotationApiBaseUrl uses the dedicated Next annotation API on the server", () => {
  withoutBrowser(() => {
    assert.equal(getAnnotationApiBaseUrl(), "/api/annotations");
  });
});

