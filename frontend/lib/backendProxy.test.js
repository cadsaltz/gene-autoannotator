import assert from "node:assert/strict";
import test from "node:test";

import { fetchBackendResponse } from "./backendProxy.js";

test("fetchBackendResponse returns service unavailable when FastAPI cannot be reached", async () => {
  const response = await fetchBackendResponse(
    new URL("http://127.0.0.1:8000/health"),
    { method: "GET", headers: new Headers() },
    async () => {
      throw new TypeError("fetch failed", {
        cause: Object.assign(new Error("connect ECONNREFUSED 127.0.0.1:8000"), {
          code: "ECONNREFUSED",
        }),
      });
    },
  );
  const payload = await response.json();

  assert.equal(response.status, 503);
  assert.equal(payload.detail, "Backend API is unavailable");
  assert.match(payload.message, /ECONNREFUSED|fetch failed/);
});

test("fetchBackendResponse forwards Set-Cookie via getSetCookie", async () => {
  const upstream = {
    status: 200,
    statusText: "OK",
    body: JSON.stringify({ ok: true }),
    headers: {
      getSetCookie() {
        return ["ga_session=abc; Path=/; HttpOnly; SameSite=Lax"];
      },
      entries() {
        return [["content-type", "application/json"]].values();
      },
    },
  };

  const response = await fetchBackendResponse(
    new URL("http://127.0.0.1:8000/auth/verify"),
    { method: "POST", headers: new Headers() },
    async () => upstream,
  );

  assert.equal(response.status, 200);
  assert.deepEqual(response.headers.getSetCookie(), [
    "ga_session=abc; Path=/; HttpOnly; SameSite=Lax",
  ]);
});
