from dataclasses import dataclass

@dataclass(frozen=True)
class GoCandidate:
    id: str
    name: str
    aspect: str
    definition: str
    score: float
    source: str

@dataclass(frozen=True)
class ResolvedGoTerm:
    id: str
    name: str
    aspect: str
    confidence: float
    method: str
    sources: tuple[str, ...]
    agreement: str | None = None

@dataclass(frozen=True)
class GoResolutionResult:
    go_terms: tuple[ResolvedGoTerm, ...]
    method: str
    queries: tuple[str, ...]
    shortlist: tuple[GoCandidate, ...]
    votes: tuple[dict, ...] = ()
    notes: str = ''
