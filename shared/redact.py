import re

_URL_SECRET_PARAM = re.compile(r"(?i)(api_key=)[^&\s'\"<>#]+")


def redact_url_secrets(text):
    """Mask secret query values (e.g. NCBI ``api_key=``) in URLs or error text."""
    if not text:
        return text
    return _URL_SECRET_PARAM.sub(r"\1REDACTED", str(text))
