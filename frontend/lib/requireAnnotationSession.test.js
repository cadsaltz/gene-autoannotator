import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { requireAnnotationSession } from "./requireAnnotationSession.js";

const originalBackendApiBaseUrl = process.env.BACKEND_API_BASE_URL;

afterEach(() => {
  if (originalBackendApiBaseUrl === undefined) {
    delete process.env.BACKEND_API_BASE_URL;
  } else {
    process.env.BACKEND_API_BASE_URL = originalBackendApiBaseUrl;
  }
});

const ADMIN = { id: "a1", email: "admin@example.org", role: "admin", status: "active" };
const USER = { id: "u1", email: "user@example.org", role: "user", status: "active" };

function request(cookie = "ga_session=tok") {
  return { headers: new Headers(cookie ? { cookie } : {}) };
}

function fakeFetch(status, payload) {
  return async () => ({ ok: status >= 200 && status < 300, status, json: async () => payload });
}

test("requireAnnotationSession returns the active user without a response", async () => {
  process.env.BACKEND_API_BASE_URL = "http://backend.test";
  const access = await requireAnnotationSession(request(), { fetchImpl: fakeFetch(200, USER) });

  assert.deepEqual(access, { user: USER, response: null });
});

test("requireAnnotationSession returns 401 when signed out", async () => {
  const access = await requireAnnotationSession(request(""), { fetchImpl: fakeFetch(200, USER) });

  assert.equal(access.user, null);
  assert.equal(access.response.status, 401);
  assert.deepEqual(await access.response.json(), { detail: "Authentication required" });
});

test("requireAnnotationSession returns 403 for suspended accounts", async () => {
  const access = await requireAnnotationSession(request(), {
    fetchImpl: fakeFetch(403, { detail: "Account suspended" }),
  });

  assert.equal(access.response.status, 403);
  assert.deepEqual(await access.response.json(), { detail: "Account suspended" });
});

test("requireAnnotationSession returns 401 when the backend is unreachable", async () => {
  const access = await requireAnnotationSession(request(), {
    fetchImpl: async () => {
      throw new TypeError("fetch failed");
    },
  });

  assert.equal(access.response.status, 401);
});

test("requireAnnotationSession admin mode rejects regular users with 403", async () => {
  const access = await requireAnnotationSession(request(), {
    admin: true,
    fetchImpl: fakeFetch(200, USER),
  });

  assert.equal(access.response.status, 403);
  assert.deepEqual(await access.response.json(), { detail: "Admin access required" });
});

test("requireAnnotationSession admin mode still returns 401 when signed out", async () => {
  const access = await requireAnnotationSession(request(""), {
    admin: true,
    fetchImpl: fakeFetch(200, ADMIN),
  });

  assert.equal(access.response.status, 401);
});

test("requireAnnotationSession admin mode admits admins", async () => {
  const access = await requireAnnotationSession(request(), {
    admin: true,
    fetchImpl: fakeFetch(200, ADMIN),
  });

  assert.deepEqual(access, { user: ADMIN, response: null });
});
