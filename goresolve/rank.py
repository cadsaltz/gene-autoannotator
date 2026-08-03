from collections.abc import Callable
from typing import Any

from goresolve.types import GoCandidate

RankFn = Callable[[str, str], dict[str, Any]]


def build_ranker_prompt(
    *,
    function: str | None,
    functional_category: list[str] | None,
    shortlist: list[GoCandidate],
    gene_id: str | None = None,
    gene_name: str | None = None,
) -> str:
    lines = [
        'You are a Gene Ontology curator. Select GO terms that best describe the gene function.',
        '',
    ]

    if gene_id or gene_name:
        gene_bits = [part for part in (gene_id, gene_name) if part]
        lines.extend([f'Gene: {" / ".join(gene_bits)}', ''])

    if function and function.strip():
        lines.extend([f'Function: {function.strip()}', ''])

    if functional_category:
        categories = [item.strip() for item in functional_category if isinstance(item, str) and item.strip()]
        if categories:
            lines.extend([f'Functional categories: {", ".join(categories)}', ''])

    lines.extend([
        'CANDIDATE LIST (ONLY choose GO IDs from the CANDIDATE LIST):',
    ])
    for candidate in shortlist:
        lines.append(
            f'- {candidate.id} | {candidate.name} | {candidate.aspect} | {candidate.definition}'
        )

    lines.extend([
        '',
        'Return JSON with this shape:',
        '{"go_terms": [{"id": "GO:...", "supported_by": ["query text"], "reason": "brief justification"}]}',
        '',
        'Rules:',
        '- ONLY choose GO IDs from the CANDIDATE LIST above.',
        '- Order selected terms from most to least relevant.',
        '- Omit terms that do not apply.',
        '- Prefer the most specific term that is clearly supported by the function text.',
        '- If the function says the gene regulates/modulates a process, prefer "regulation of …" terms over the bare process term.',
        '- Do not select a broad process term merely because a functional_category string matches its name exactly; require support from the function description.',
        '  An exact category label match is not sufficient evidence on its own.',
        '- Prefer a molecular_function + biological_process pair when both are clearly supported (e.g. chaperone activity + protein folding; transporter activity + ion transport).',
        '- Prefer fewer high-confidence terms over many weak or redundant ones.',
        '- If both a general and a specific term apply, prefer the specific term (the pipeline may drop parents later).',
        '- Each go_terms entry must include id; supported_by and reason are optional but encouraged.',
    ])
    return '\n'.join(lines)


def filter_ids_to_shortlist(ids: list[str], shortlist: list[GoCandidate]) -> list[str]:
    allowed = {candidate.id for candidate in shortlist}
    return [go_id for go_id in ids if go_id in allowed]


def ollama_rank_fn(prompt: str, model: str) -> dict[str, Any]:
    import json

    import ollama

    schema = {
        'type': 'object',
        'properties': {
            'go_terms': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'id': {'type': 'string'},
                        'supported_by': {'type': 'array', 'items': {'type': 'string'}},
                        'reason': {'type': 'string'},
                    },
                    'required': ['id'],
                },
            }
        },
        'required': ['go_terms'],
    }
    response = ollama.chat(
        model=model,
        messages=[{'role': 'user', 'content': prompt}],
        format=schema,
        options={'temperature': 0},
    )
    return json.loads(response['message']['content'])


def rank_go_terms(
    *,
    function: str | None,
    functional_category: list[str] | None,
    shortlist: list[GoCandidate],
    model: str,
    rank_fn: RankFn | None = None,
    gene_id: str | None = None,
    gene_name: str | None = None,
) -> list[str]:
    prompt = build_ranker_prompt(
        function=function,
        functional_category=functional_category,
        shortlist=shortlist,
        gene_id=gene_id,
        gene_name=gene_name,
    )
    call_rank = rank_fn or ollama_rank_fn
    payload = call_rank(prompt, model)
    raw_ids = [
        term['id']
        for term in payload.get('go_terms', [])
        if isinstance(term, dict) and term.get('id')
    ]
    return filter_ids_to_shortlist(raw_ids, shortlist)
