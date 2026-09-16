import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { getMe, login, logout, signup, verifyCode } from "./authApi.js";

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

test("OTP auth helpers call signup, login, verify, me, and logout", async () => {
  process.env.BACKEND_API_BASE_URL = "http://backend.test";
  const calls = [];
  mockFetch((url, options) => {
    calls.push({ url, options });
    return { ok: true };
  });

  await signup("user@example.com", "alice");
  await signup("user@example.com");
  await login("user@example.com");
  await verifyCode("user@example.com", "123456");
  await getMe();
  await logout();

  assert.deepEqual(
    calls.map((call) => [call.url, call.options.method, call.options.body, call.options.credentials]),
    [
      [
        "http://backend.test/auth/signup",
        "POST",
        JSON.stringify({ email: "user@example.com", username: "alice" }),
        "include",
      ],
      [
        "http://backend.test/auth/signup",
        "POST",
        JSON.stringify({ email: "user@example.com", username: null }),
        "include",
      ],
      [
        "http://backend.test/auth/login",
        "POST",
        JSON.stringify({ email: "user@example.com" }),
        "include",
      ],
      [
        "http://backend.test/auth/verify",
        "POST",
        JSON.stringify({ email: "user@example.com", code: "123456" }),
        "include",
      ],
      ["http://backend.test/auth/me", undefined, undefined, "include"],
      ["http://backend.test/auth/logout", "POST", undefined, "include"],
    ],
  );
});
