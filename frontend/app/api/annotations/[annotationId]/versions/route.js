import { NextResponse } from "next/server";

import { getStoredAnnotationVersions } from "../../../../../lib/annotationStore";
import { getAnnotationsCollection } from "../../../../../lib/mongodb";
import { requireAnnotationSession } from "../../../../../lib/requireAnnotationSession";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(request, context) {
  const unauthorized = await requireAnnotationSession(request);
  if (unauthorized) return unauthorized;

  const params = await context.params;

  try {
    const collection = await getAnnotationsCollection();
    const versions = await getStoredAnnotationVersions(collection, params.annotationId);
    if (versions === null) {
      return NextResponse.json({ detail: "Annotation not found" }, { status: 404 });
    }
    return NextResponse.json({ annotation_id: params.annotationId, versions });
  } catch (error) {
    return NextResponse.json({ detail: error.message }, { status: 503 });
  }
}
