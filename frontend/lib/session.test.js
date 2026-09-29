import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { getServerSession, requireAdminPage } from "./session.js";

const originalBackendApiBaseUrl = process.env.BACKEND_API_BASE_URL;

afterEach(() => {
  if (originalBackendApiBaseUrl === undefined) {
    delete process.env.BACKEND_API_BASE_URL;
  } else {
    process.env.BACKEND_API_BASE_URL = originalBackendApiBaseUrl;
  }
});

const ADMIN = {
  id: "u1",
  email: "admin@example.org",
  username: "admin",
  email_verified: true,
  role: "admin",
  status: "active",
};
const USER = { ...ADMIN, id: "u2", email: "user@example.org", role: "user" };

function requestWithCookie(cookie) {
  return { headers: new Headers(cookie ? { cookie } : {}) };
}

function cookieStore(entries) {
  return {
    get: (name) => entries.find((entry) => entry.name === name),
    getAll: () => entries,
  };
}

function fakeFetch(status, payload, calls = []) {
  return async (url, options) => {
    calls.push({ url, options });
    return { ok: status >= 200 && status < 300, status, json: async () => payload };
  };
}

class RedirectSignal extends Error {
  constructor(location) {
    super(`redirect:${location}`);
    this.location = location;
  }
}

function throwingRedirect(location) {
  throw new RedirectSignal(location);
}

test("getServerSession forwards the request cookie to backend /auth/me", async () => {
  process.env.BACKEND_API_BASE_URL = "http://backend.test";
  const calls = [];

  const session = await getServerSession(
    requestWithCookie("ga_session=tok123; other=1"),
    fakeFetch(200, ADMIN, calls),
  );

  assert.deepEqual(session, { user: ADMIN });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "http://backend.test/auth/me");
  assert.equal(calls[0].options.headers.Cookie, "ga_session=tok123; other=1");
  assert.equal(calls[0].options.cache, "no-store");
});

test("getServerSession accepts a next/headers cookie store", async () => {
  process.env.BACKEND_API_BASE_URL = "http://backend.test";
  const calls = [];

  const session = await getServerSession(
    cookieStore([{ name: "ga_session", value: "tok456" }]),
    fakeFetch(200, USER, calls),
  );

  assert.deepEqual(session, { user: USER });
  assert.equal(calls[0].options.headers.Cookie, "ga_session=tok456");
});

test("getServerSession skips the backend when there is no session cookie", async () => {
  const calls = [];

  const session = await getServerSession(requestWithCookie(""), fakeFetch(200, USER, calls));

  assert.deepEqual(session, { user: null, reason: "signed_out" });
  assert.equal(calls.length, 0);
});

test("getServerSession reports signed_out on 401", async () => {
  const session = await getServerSession(
    requestWithCookie("ga_session=expired"),
    fakeFetch(401, { detail: "Not authenticated" }),
  );

  assert.deepEqual(session, { user: null, reason: "signed_out" });
});

test("getServerSession reports suspended on 403", async () => {
  const session = await getServerSession(
    requestWithCookie("ga_session=tok"),
    fakeFetch(403, { detail: "Account suspended" }),
  );

  assert.deepEqual(session, { user: null, reason: "suspended" });
});

test("getServerSession reports unavailable when the backend cannot be reached", async () => {
  const session = await getServerSession(requestWithCookie("ga_session=tok"), async () => {
    throw new TypeError("fetch failed");
  });

  assert.deepEqual(session, { user: null, reason: "unavailable" });
});

test("requireAdminPage returns the admin user", async () => {
  const user = await requireAdminPage("/fleet", {
    cookieSource: requestWithCookie("ga_session=tok"),
    fetchImpl: fakeFetch(200, ADMIN),
    redirectImpl: throwingRedirect,
  });

  assert.deepEqual(user, ADMIN);
});

test("requireAdminPage redirects regular users to /jobs", async () => {
  await assert.rejects(
    requireAdminPage("/fleet", {
      cookieSource: requestWithCookie("ga_session=tok"),
      fetchImpl: fakeFetch(200, USER),
      redirectImpl: throwingRedirect,
    }),
    (error) => error.location === "/jobs",
  );
});

test("requireAdminPage redirects suspended accounts to /jobs", async () => {
  await assert.rejects(
    requireAdminPage("/fleet", {
      cookieSource: requestWithCookie("ga_session=tok"),
      fetchImpl: fakeFetch(403, { detail: "Account suspended" }),
      redirectImpl: throwingRedirect,
    }),
    (error) => error.location === "/jobs",
  );
});

test("requireAdminPage redirects signed-out visitors to login with next", async () => {
  await assert.rejects(
    requireAdminPage("/admin/users", {
      cookieSource: requestWithCookie(""),
      fetchImpl: fakeFetch(401, {}),
      redirectImpl: throwingRedirect,
    }),
    (error) => error.location === "/login?next=%2Fadmin%2Fusers",
  );
});

test("requireAdminPage sanitizes the next path", async () => {
  await assert.rejects(
    requireAdminPage("//evil.example", {
      cookieSource: requestWithCookie(""),
      fetchImpl: fakeFetch(401, {}),
      redirectImpl: throwingRedirect,
    }),
    (error) => error.location === "/login?next=%2Fjobs",
  );
});
