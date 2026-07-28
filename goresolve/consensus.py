import math
from collections import Counter


def agreement_threshold(n_candidates: int) -> int:
    if n_candidates < 1:
        return 1
    return max(1, math.ceil(n_candidates / 2))


def majority_go_ids(votes: list[list[str]], *, n_models: int | None = None):
    n = n_models if n_models is not None else len(votes)
    threshold = agreement_threshold(n)
    counts = Counter()
    for vote in votes:
        for go_id in set(vote):  # per-model unique
            counts[go_id] += 1
    winners = []
    for go_id, count in counts.most_common():
        if count >= threshold:
            winners.append((go_id, f'{count}/{n}', count / n))
    return winners
