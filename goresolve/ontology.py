import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GoTermRecord:
    id: str
    name: str
    aspect: str
    definition: str
    synonyms: tuple[str, ...] = ()


@dataclass(frozen=True)
class GoOntology:
    terms: dict[str, GoTermRecord]
    label_index: dict[str, set[str]]
    parents: dict[str, set[str]]

    def document_text(self, go_id: str) -> str:
        term = self.terms[go_id]
        parts = [term.name, *term.synonyms]
        if term.definition:
            parts.append(term.definition)
        return ' '.join(parts)

    def iter_embed_documents(self) -> list[tuple[str, str]]:
        return [(go_id, self.document_text(go_id)) for go_id in self.terms]


def load_go_ontology(path: str | Path) -> GoOntology:
    path = Path(path)
    if not path.exists():
        return GoOntology(terms={}, label_index={}, parents={})
    with path.open() as obo_file:
        return parse_go_obo(obo_file)


def parse_go_obo(lines) -> GoOntology:
    terms: dict[str, GoTermRecord] = {}
    label_index: dict[str, set[str]] = {}
    parents: dict[str, set[str]] = {}
    term = None

    for raw_line in lines:
        line = raw_line.strip()
        if line == '[Term]':
            _add_term_to_ontology(term, terms, label_index, parents)
            term = _new_term()
            continue
        if line.startswith('['):
            _add_term_to_ontology(term, terms, label_index, parents)
            term = None
            continue
        if term is None or not line:
            continue
        _apply_obo_line(term, line)

    _add_term_to_ontology(term, terms, label_index, parents)
    return GoOntology(terms=terms, label_index=label_index, parents=parents)


def _new_term():
    return {
        'id': None,
        'name': None,
        'aspect': '',
        'definition': '',
        'synonyms': [],
        'parents': set(),
        'is_obsolete': False,
    }


def _apply_obo_line(term, line):
    if line.startswith('id: '):
        term['id'] = line.removeprefix('id: ').strip()
    elif line.startswith('name: '):
        term['name'] = line.removeprefix('name: ').strip()
    elif line.startswith('namespace: '):
        term['aspect'] = line.removeprefix('namespace: ').strip()
    elif line.startswith('def: '):
        match = re.search(r'"([^"]+)"', line)
        if match:
            term['definition'] = match.group(1)
    elif line.startswith('is_a: '):
        term['parents'].add(line.removeprefix('is_a: ').split()[0])
    elif line == 'is_obsolete: true':
        term['is_obsolete'] = True
    elif line.startswith('synonym: '):
        match = re.search(r'"([^"]+)"', line)
        if match:
            term['synonyms'].append(match.group(1))


def _add_term_to_ontology(term, terms, label_index, parents):
    if not term or not term['id'] or term['is_obsolete']:
        return

    term_id = term['id']
    record = GoTermRecord(
        id=term_id,
        name=term['name'] or '',
        aspect=term['aspect'],
        definition=term['definition'],
        synonyms=tuple(term['synonyms']),
    )
    terms[term_id] = record
    parents[term_id] = set(term['parents'])

    for label in [term['name'], *term['synonyms']]:
        if not label:
            continue
        label_index.setdefault(_normalize_label(label), set()).add(term_id)


def _normalize_label(label: str) -> str:
    label = re.sub(r'\([^)]*pmid[^)]*\)', '', label, flags=re.IGNORECASE)
    label = re.sub(r'pmid:?\s*\d+', '', label, flags=re.IGNORECASE)
    label = label.lower()
    label = label.replace('&', ' and ')
    label = label.replace('/', ' ')
    label = label.replace('-', ' ')
    label = re.sub(r'[^a-z0-9]+', ' ', label)
    return ' '.join(label.split())
