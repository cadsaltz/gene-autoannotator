const HOP_BY_HOP_HEADERS = new Set([
  "connection",
  "content-encoding",
  "content-length",
  "keep-alive",
  "transfer-encoding",
  "upgrade",
]);

export function copyProxyHeaders(headers) {
  // Hop-by-hop headers describe one network connection and can break streamed
  // proxy responses if forwarded unchanged.
  const copied = new Headers();
  for (const [key, value] of headers.entries()) {
    if (HOP_BY_HOP_HEADERS.has(key.toLowerCase())) {
      continue;
    }
    // set-cookie is handled separately via getSetCookie() — the Headers
    // iterator can drop or join cookies incorrectly.
    if (key.toLowerCase() === "set-cookie") {
      continue;
    }
    copied.append(key, value);
  }

  const getSetCookie = typeof headers.getSetCookie === "function" ? headers.getSetCookie.bind(headers) : null;
  if (getSetCookie) {
    for (const cookie of getSetCookie()) {
      copied.append("set-cookie", cookie);
    }
  }
  return copied;
}

function backendUnavailableMessage(error) {
  return error.cause?.message || error.message || "Backend API request failed";
}

export async function fetchBackendResponse(backendUrl, init, fetchImpl = fetch) {
  try {
    const response = await fetchImpl(backendUrl, init);
    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: copyProxyHeaders(response.headers),
    });
  } catch (error) {
    return Response.json(
      {
        detail: "Backend API is unavailable",
        message: backendUnavailableMessage(error),
      },
      { status: 503 },
    );
  }
}
