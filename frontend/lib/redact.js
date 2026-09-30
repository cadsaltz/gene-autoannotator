// Matches `api_key=` and its URL-encoded spellings (`api_key%3D`, `api%5Fkey=`).
// The value stops at URL/prose delimiters, a backslash (JSON escapes), or an
// encoded `&` (`%26`) so neighbouring query params survive.
const URL_SECRET_PARAM = /(api(?:_|%5F)key(?:=|%3D))(?:(?!%26)[^&\s'"<>#),;\\])+/gi;

const MONGO_CONNECTION_STRING = /mongodb(?:\+srv)?:\/\/[^\s'"<>]+/gi;

/** Mask secret query values (e.g. NCBI `api_key=`) in URLs or error text. */
export function redactUrlSecrets(text) {
  if (!text) return text;
  return String(text).replace(URL_SECRET_PARAM, "$1REDACTED");
}

/** Copy a JSON-like value with every string (keys included) passed through redactUrlSecrets. */
export function redactSecretsIn(value) {
  if (typeof value === "string") return redactUrlSecrets(value);
  if (Array.isArray(value)) return value.map(redactSecretsIn);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [redactUrlSecrets(key), redactSecretsIn(item)]),
    );
  }
  return value;
}

export function redactConnectionStrings(text) {
  if (!text) return text;
  return String(text).replace(MONGO_CONNECTION_STRING, "mongodb://[redacted]");
}
