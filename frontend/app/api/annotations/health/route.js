import { NextResponse } from "next/server";

import { getNextAnnotationHealth } from "../../../../lib/mongodb";
import { requireAnnotationSession } from "../../../../lib/requireAnnotationSession";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(request) {
  const access = await requireAnnotationSession(request, { admin: true });
  if (access.response) return access.response;

  const health = await getNextAnnotationHealth();
  const status = health.status === "ok" ? 200 : 503;
  return NextResponse.json(health, { status });
}
