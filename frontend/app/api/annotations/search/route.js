import { NextResponse } from "next/server";

import { searchStoredAnnotations } from "../../../../lib/annotationStore";
import { getAnnotationsCollection } from "../../../../lib/mongodb";
import { requireAnnotationSession } from "../../../../lib/requireAnnotationSession";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(request) {
  const unauthorized = await requireAnnotationSession(request);
  if (unauthorized) return unauthorized;

  const { searchParams } = new URL(request.url);
  const query = searchParams.get("query") || "";
  const requestedLimit = Number(searchParams.get("limit") || 20);
  const limit = Math.min(100, Math.max(1, Number.isFinite(requestedLimit) ? requestedLimit : 20));

  try {
    const collection = await getAnnotationsCollection();
    const matches = await searchStoredAnnotations(collection, query, limit);
    return NextResponse.json({ query, matches });
  } catch (error) {
    return NextResponse.json({ detail: error.message }, { status: 503 });
  }
}
