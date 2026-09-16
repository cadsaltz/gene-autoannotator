import { NextResponse } from "next/server";

import { getNextAnnotationHealth } from "../../../../lib/mongodb";
import { requireAnnotationSession } from "../../../../lib/requireAnnotationSession";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(request) {
  const unauthorized = await requireAnnotationSession(request);
  if (unauthorized) return unauthorized;

  const health = await getNextAnnotationHealth();
  const status = health.status === "ok" ? 200 : 503;
  return NextResponse.json(health, { status });
}
