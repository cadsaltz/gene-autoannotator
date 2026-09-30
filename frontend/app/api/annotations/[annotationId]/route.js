import { NextResponse } from "next/server";

import { getStoredAnnotation } from "../../../../lib/annotationStore";
import { getAnnotationsCollection } from "../../../../lib/mongodb";
import { requireAnnotationSession } from "../../../../lib/requireAnnotationSession";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(request, context) {
  const access = await requireAnnotationSession(request);
  if (access.response) return access.response;

  const params = await context.params;

  try {
    const collection = await getAnnotationsCollection();
    const annotation = await getStoredAnnotation(collection, params.annotationId, {
      includeJobDetails: access.user.role === "admin",
    });
    if (annotation === null) {
      return NextResponse.json({ detail: "Annotation not found" }, { status: 404 });
    }
    return NextResponse.json(annotation);
  } catch {
    return NextResponse.json({ detail: "Annotation storage is unavailable" }, { status: 503 });
  }
}
