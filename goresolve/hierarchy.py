from goresolve.ontology import GoOntology


def _ancestors(go_id: str, ontology: GoOntology) -> set[str]:
    ancestors: set[str] = set()
    stack = list(ontology.parents.get(go_id, ()))
    while stack:
        parent = stack.pop()
        if parent in ancestors:
            continue
        ancestors.add(parent)
        stack.extend(ontology.parents.get(parent, ()))
    return ancestors


def drop_ancestor_terms(
    go_ids: list[str],
    ontology: GoOntology,
) -> list[str]:
    selected_ids = set(go_ids)
    return [
        go_id
        for go_id in go_ids
        if not any(
            go_id in _ancestors(other_id, ontology)
            for other_id in selected_ids
            if other_id != go_id
        )
    ]
