import re

# Matches `api_key=` and its URL-encoded spellings (`api_key%3D`, `api%5Fkey=`).
# The value stops at URL/prose delimiters, a backslash (JSON escapes), or an
# encoded `&` (`%26`) so neighbouring query params survive.
_URL_SECRET_PARAM = re.compile(
    r"(?i)(api(?:_|%5F)key(?:=|%3D))(?:(?!%26)[^&\s'\"<>#),;\\])+"
)


def redact_url_secrets(text):
    """Mask secret query values (e.g. NCBI ``api_key=``) in URLs or error text."""
    if not text:
        return text
    return _URL_SECRET_PARAM.sub(r"\1REDACTED", str(text))


def redact_secrets_in(value):
    """Return a copy of a JSON-like value with every string passed through
    ``redact_url_secrets``; non-string leaves are returned unchanged."""
    if isinstance(value, str):
        return redact_url_secrets(value)
    if isinstance(value, dict):
        return {redact_secrets_in(key): redact_secrets_in(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_secrets_in(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_secrets_in(item) for item in value)
    return value
