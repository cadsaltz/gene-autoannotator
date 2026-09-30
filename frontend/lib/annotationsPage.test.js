import assert from "node:assert/strict";
import test from "node:test";

import { ANNOTATION_SEARCH_UNAVAILABLE, loadAnnotationsPage } from "./annotationsPage.js";

const USER = { id: "u1", role: "user", status: "active" };

function failingSearch() {
  throw new Error("search should not run");
}

test("signed-out visitors are redirected to login with next", async () => {
  const page = await loadAnnotationsPage({
    session: { user: null, reason: "signed_out" },
    query: "",
    search: failingSearch,
  });

  assert.deepEqual(page, { redirectTo: "/login?next=%2Fannotations" });
});

test("signed-out redirect keeps the search query", async () => {
  const page = await loadAnnotationsPage({
    session: { user: null, reason: "signed_out" },
    query: "dna A",
    search: failingSearch,
  });

  assert.deepEqual(page, { redirectTo: "/login?next=%2Fannotations%3Fquery%3Ddna%2520A" });
});

test("suspended accounts get no search results", async () => {
  const page = await loadAnnotationsPage({
    session: { user: null, reason: "suspended" },
    query: "dnaA",
    search: failingSearch,
  });

  assert.deepEqual(page, { matches: [], message: "" });
});

test("an unavailable session backend does not run the search", async () => {
  const page = await loadAnnotationsPage({
    session: { user: null, reason: "unavailable" },
    query: "dnaA",
    search: failingSearch,
  });

  assert.deepEqual(page, { matches: [], message: ANNOTATION_SEARCH_UNAVAILABLE });
});

test("active users with a query get search matches", async () => {
  const page = await loadAnnotationsPage({
    session: { user: USER },
    query: "dnaA",
    search: async (query) => [{ id: `hit:${query}` }],
  });

  assert.deepEqual(page, { matches: [{ id: "hit:dnaA" }], message: "" });
});

test("active users without a query skip the search", async () => {
  const page = await loadAnnotationsPage({ session: { user: USER }, query: "", search: failingSearch });

  assert.deepEqual(page, { matches: [], message: "" });
});

test("database errors become a generic message", async () => {
  const page = await loadAnnotationsPage({
    session: { user: USER },
    query: "dnaA",
    search: async () => {
      throw new Error("connect ECONNREFUSED mongodb://admin:pw@db:27017");
    },
  });

  assert.deepEqual(page, { matches: [], message: "Annotation search is unavailable." });
});
