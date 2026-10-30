from __future__ import annotations

COLUMNS = (
    'gene_id',
    'name',
    'function',
    'functional_category',
    'drug_susc_impact',
    'infection_impact',
    'go_terms',
)
EXCEL_CELL_LIMIT = 32767
LIST_SEP = '; '

_FALSEY_NOT = {None, '', '0', 'false', 'False', 'no', 'No', False, 0}


def format_string(value: object) -> str:
    if value is None:
        return ''
    if isinstance(value, str) and value.strip().lower() == 'null':
        return ''
    text = str(value).strip()
    return '' if text.lower() == 'null' else text


def format_string_list(value: object) -> str:
    if value is None or value == []:
        return ''
    if isinstance(value, str):
        return format_string(value)
    parts = [format_string(item) for item in value]
    return LIST_SEP.join(part for part in parts if part)


def _is_not_true(value: object) -> bool:
    return value not in _FALSEY_NOT


def _go_id_and_name(item: object) -> tuple[str, str] | None:
    if not isinstance(item, dict):
        return None
    if _is_not_true(item.get('is_not')):
        return None
    go_id = format_string(item.get('id') or item.get('go_id'))
    name = format_string(item.get('name') or item.get('go_term_name'))
    if not go_id:
        return None
    if not go_id.upper().startswith('GO:'):
        go_id = f'GO:{go_id}'
    return go_id, name


def format_go_terms(value: object) -> str:
    if value is None:
        return ''
    if isinstance(value, dict):
        value = [value]
    unique: dict[str, str] = {}
    for item in value:
        parsed = _go_id_and_name(item)
        if parsed is None:
            continue
        go_id, name = parsed
        unique.setdefault(go_id, name)
    return LIST_SEP.join(
        f'{go_id} {name}'.strip() if name else go_id
        for go_id, name in sorted(unique.items())
    )


def empty_row(gene_id: str) -> dict[str, str]:
    row = {key: '' for key in COLUMNS}
    row['gene_id'] = gene_id
    return row


def annotation_to_row(payload: dict) -> dict[str, str]:
    row = empty_row(format_string(payload.get('gene_id')))
    row['name'] = format_string(payload.get('name'))
    row['function'] = format_string(payload.get('function'))
    row['functional_category'] = format_string_list(payload.get('functional_category'))
    row['drug_susc_impact'] = format_string(payload.get('drug_susc_impact'))
    row['infection_impact'] = format_string(payload.get('infection_impact'))
    row['go_terms'] = format_go_terms(payload.get('go_terms'))
    return row


def truncate_cell(text: str) -> tuple[str, bool]:
    if len(text) <= EXCEL_CELL_LIMIT:
        return text, False
    return text[:EXCEL_CELL_LIMIT], True
