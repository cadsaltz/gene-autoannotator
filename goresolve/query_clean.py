import re

_PMID_RE = re.compile(r'\(?\s*PMID\s*:?\s*\d+\s*\)?', re.IGNORECASE)
_PMC_RE = re.compile(r'\(?\s*PMC\s*:?\s*PMC?\d+\s*\)?', re.IGNORECASE)
# also bare "PMC5017210"
_PMC_BARE_RE = re.compile(r'\bPMC\d+\b', re.IGNORECASE)


def clean_query_text(text: str) -> str:
    cleaned = _PMID_RE.sub(' ', text)
    cleaned = _PMC_RE.sub(' ', cleaned)
    cleaned = _PMC_BARE_RE.sub(' ', cleaned)
    cleaned = re.sub(r'\(\s*\)', ' ', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip(' ,;.')
    return cleaned
