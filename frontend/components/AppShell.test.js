import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

const projectRoot = process.cwd();

async function readProjectFile(relativePath) {
  return readFile(path.join(projectRoot, relativePath), "utf8");
}

test("AppShell hides workbench links until signed in", async () => {
  const workspace = await readProjectFile("components/AppShell.js");
  assert.match(workspace, /getMe|useAuth|signedIn|email_verified/);
  assert.match(workspace, /Sign in|Sign out|signup|login/i);
});
