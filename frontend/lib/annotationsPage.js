import { loginPathFor } from "./authPaths.js";

export const ANNOTATION_SEARCH_UNAVAILABLE = "Annotation search is unavailable.";

function annotationsPath(query) {
  return query ? `/annotations?query=${encodeURIComponent(query)}` : "/annotations";
}

/**
 * Server-side data for /annotations. Returns `{ redirectTo }` for signed-out visitors,
 * otherwise `{ matches, message }`; the search only runs for an active user.
 */
export async function loadAnnotationsPage({ session, query, search }) {
  if (!session.user) {
    if (session.reason === "signed_out") return { redirectTo: loginPathFor(annotationsPath(query)) };
    if (session.reason === "unavailable" && query) {
      return { matches: [], message: ANNOTATION_SEARCH_UNAVAILABLE };
    }
    return { matches: [], message: "" };
  }
  if (!query) return { matches: [], message: "" };

  try {
    return { matches: await search(query), message: "" };
  } catch {
    return { matches: [], message: ANNOTATION_SEARCH_UNAVAILABLE };
  }
}
