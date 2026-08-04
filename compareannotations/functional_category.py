"""Graph-aware scoring for functional category annotations.

When a real go-basic.obo file is available, labels and synonyms are resolved
against official GO terms. The curated aliases remain as bridges for existing
project labels like "information pathways" that are useful but not GO names.
"""

import os
import re
from collections import deque
from dataclasses import dataclass


SAME_TERM_SCORE = 1.0
GENERATED_DESCENDANT_SCORE = 0.95
GENERATED_ANCESTOR_SCORE = 0.65
CLOSE_SIBLING_SCORE = 0.4

UNINFORMATIVE_SHARED_ANCESTORS = frozenset({
	'GO:0008150',  # biological_process
	'GO:0003674',  # molecular_function
	'GO:0005575',  # cellular_component
	'GO:0009987',  # cellular process
})

GO_BASIC_OBO_ENV_VAR = 'GO_BASIC_OBO_PATH'
DEFAULT_GO_BASIC_OBO_PATH = os.path.join('data', 'go-basic.obo')

_default_ontology = None

CATEGORY_ALIASES = {
	'information pathways': {'GO:0006259', 'GO:0006351', 'GO:0006412'},
	'dna replication repair': {'GO:0006260', 'GO:0006281'},
	'dna replication': {'GO:0006260'},
	'replication': {'GO:0006260'},
	'dna replication initiation': {'GO:0006270'},
	'initiation of chromosome replication': {'GO:0006270'},
	'initiator protein': {'GO:0006260'},
	'dna repair': {'GO:0006281'},
	'transcription': {'GO:0006351'},
	'translation': {'GO:0006412'},
	'protein synthesis': {'GO:0006412'},
	'growth regulation': {'GO:0040007'},
	'regulation': {'GO:0065007'},

	'cell wall and cell processes': {
		'GO:0071555',
		'GO:0006810',
		'GO:0055085',
		'GO:0006875',
		'GO:0006950',
	},
	'cell wall': {'GO:0071555'},
	'cell wall organization': {'GO:0071555'},
	'transport': {'GO:0006810'},
	'membrane transport': {'GO:0055085'},
	'transmembrane transport': {'GO:0055085'},
	'ion transport': {'GO:0006811'},
	'metal transport': {'GO:0000041'},
	'metal homeostasis': {'GO:0006875'},
	'copper homeostasis': {'GO:0055070'},
	'heavy metal efflux': {'GO:0000041'},
	'zinc efflux': {'GO:0071577'},

	'intermediary metabolism and respiration': {'GO:0008152', 'GO:0045333'},
	'metabolism': {'GO:0008152'},
	'respiration': {'GO:0045333'},
	'electron transport': {'GO:0022900'},
	'hypoxia response': {'GO:0001666'},

	'lipid metabolism': {'GO:0006629'},
	'biosynthesis': {'GO:0009058'},

	'stress response': {'GO:0006950'},
	'multi metal stress response': {'GO:0006950'},
	'virulence': {'GO:0009405'},
	'host pathogen interaction': {'GO:0030383'},
	'immune response': {'GO:0006955'},
	'latent infection': {'GO:0070265'},
}

GO_PARENTS = {
	'GO:0006270': {'GO:0006260'},
	'GO:0006260': {'GO:0006259'},
	'GO:0006281': {'GO:0006259'},
	'GO:0006259': {'GO:0009987'},
	'GO:0006351': {'GO:0009987'},
	'GO:0006412': {'GO:0009987'},
	'GO:0040007': {'GO:0009987'},
	'GO:0065007': {'GO:0008150'},

	'GO:0071555': {'GO:0009987'},
	'GO:0055085': {'GO:0006810'},
	'GO:0006811': {'GO:0006810'},
	'GO:0000041': {'GO:0006811'},
	'GO:0071577': {'GO:0000041'},
	'GO:0055070': {'GO:0006875'},
	'GO:0006875': {'GO:0009987'},
	'GO:0006810': {'GO:0009987'},

	'GO:0045333': {'GO:0008152'},
	'GO:0022900': {'GO:0045333'},
	'GO:0001666': {'GO:0006950'},
	'GO:0008152': {'GO:0008150'},
	'GO:0006629': {'GO:0008152'},
	'GO:0009058': {'GO:0008152'},

	'GO:0006950': {'GO:0008150'},
	'GO:0009405': {'GO:0006950'},
	'GO:0030383': {'GO:0009405'},
	'GO:0006955': {'GO:0008150'},
	'GO:0070265': {'GO:0008150'},
	'GO:0009987': {'GO:0008150'},
	'GO:0008150': set(),
}


@dataclass(frozen=True)
class GoOntology:
	parents: dict
	label_index: dict


def functional_category_similarity(trusted_value, generated_value, ontology=None):
	"""Return graph similarity for mapped categories, or None when fallback is needed."""
	if ontology is None:
		ontology = get_default_ontology()

	trusted_groups = _mapped_category_groups(trusted_value, ontology)
	generated_groups = _mapped_category_groups(generated_value, ontology)

	if not trusted_groups or not generated_groups:
		return None

	scores = []
	for trusted_nodes in trusted_groups:
		best = max(
			_score_node_groups(trusted_nodes, generated_nodes, ontology)
			for generated_nodes in generated_groups
		)
		scores.append(best)

	return round(sum(scores) / len(scores), 3)


def get_default_ontology():
	global _default_ontology
	if _default_ontology is not None:
		return _default_ontology

	path = os.environ.get(GO_BASIC_OBO_ENV_VAR, DEFAULT_GO_BASIC_OBO_PATH)
	_default_ontology = load_go_ontology(path)
	return _default_ontology


def load_go_ontology(path):
	if not path or not os.path.exists(path):
		return GoOntology(parents={}, label_index={})
	with open(path) as obo_file:
		return parse_go_obo(obo_file)


def parse_go_obo(lines):
	parents = {}
	label_index = {}
	term = None

	for raw_line in lines:
		line = raw_line.strip()
		if line == '[Term]':
			_add_term_to_ontology(term, parents, label_index)
			term = _new_term()
			continue
		if line.startswith('['):
			_add_term_to_ontology(term, parents, label_index)
			term = None
			continue
		if term is None or not line:
			continue
		_apply_obo_line(term, line)

	_add_term_to_ontology(term, parents, label_index)
	return GoOntology(parents=parents, label_index=label_index)


def _new_term():
	return {
		'id': None,
		'name': None,
		'synonyms': [],
		'parents': set(),
		'alt_ids': [],
		'is_obsolete': False,
	}


def _apply_obo_line(term, line):
	if line.startswith('id: '):
		term['id'] = line.removeprefix('id: ').strip()
	elif line.startswith('name: '):
		term['name'] = line.removeprefix('name: ').strip()
	elif line.startswith('alt_id: '):
		term['alt_ids'].append(line.removeprefix('alt_id: ').strip())
	elif line.startswith('is_a: '):
		term['parents'].add(line.removeprefix('is_a: ').split()[0])
	elif line.startswith('relationship: part_of '):
		term['parents'].add(line.removeprefix('relationship: part_of ').split()[0])
	elif line == 'is_obsolete: true':
		term['is_obsolete'] = True
	elif line.startswith('synonym: '):
		match = re.search(r'"([^"]+)"', line)
		if match:
			term['synonyms'].append(match.group(1))


def _add_term_to_ontology(term, parents, label_index):
	if not term or not term['id'] or term['is_obsolete']:
		return

	term_id = term['id']
	parents[term_id] = set(term['parents'])

	for label in [term['name'], *term['synonyms']]:
		if not label:
			continue
		_add_label_mapping(label_index, label, term_id)

	for alt_id in term['alt_ids']:
		_add_label_mapping(label_index, alt_id, term_id)


def _add_label_mapping(label_index, label, term_id):
	label_index.setdefault(_normalize_category(label), set()).add(term_id)


def _mapped_category_groups(value, ontology):
	groups = []
	for category in _iter_category_values(value):
		nodes = _map_category(category, ontology)
		if nodes:
			groups.append(nodes)
	return groups


def _map_category(category, ontology):
	go_id_match = re.search(r'GO:\d{7}', category.strip(), flags=re.IGNORECASE)
	if go_id_match:
		go_id = go_id_match.group(0).upper()
		if go_id in ontology.parents or go_id in GO_PARENTS:
			return {go_id}

	normalized = _normalize_category(category)
	return (
		CATEGORY_ALIASES.get(normalized)
		or ontology.label_index.get(normalized)
	)


def _iter_category_values(value):
	if value is None:
		return
	if isinstance(value, list):
		for item in value:
			if item is not None:
				yield str(item)
		return
	yield str(value)


def _normalize_category(category):
	category = re.sub(r'\([^)]*pmid[^)]*\)', '', category, flags=re.IGNORECASE)
	category = re.sub(r'pmid:?\s*\d+', '', category, flags=re.IGNORECASE)
	category = category.lower()
	category = category.replace('&', ' and ')
	category = category.replace('/', ' ')
	category = category.replace('-', ' ')
	category = re.sub(r'[^a-z0-9]+', ' ', category)
	return ' '.join(category.split())


def _score_node_groups(trusted_nodes, generated_nodes, ontology):
	return max(
		_score_nodes(trusted_node, generated_node, ontology)
		for trusted_node in trusted_nodes
		for generated_node in generated_nodes
	)


def _score_nodes(trusted_node, generated_node, ontology):
	if trusted_node == generated_node:
		return SAME_TERM_SCORE

	generated_ancestors = _ancestor_distances(generated_node, ontology)
	if trusted_node in generated_ancestors:
		if trusted_node in UNINFORMATIVE_SHARED_ANCESTORS:
			return 0.0
		return GENERATED_DESCENDANT_SCORE

	trusted_ancestors = _ancestor_distances(trusted_node, ontology)
	if generated_node in trusted_ancestors:
		if generated_node in UNINFORMATIVE_SHARED_ANCESTORS:
			return 0.0
		return GENERATED_ANCESTOR_SCORE

	shared_ancestors = (
		set(trusted_ancestors.keys())
		& set(generated_ancestors.keys())
		- UNINFORMATIVE_SHARED_ANCESTORS
	)
	if shared_ancestors:
		return CLOSE_SIBLING_SCORE

	return 0.0


def _ancestor_distances(node, ontology):
	distances = {node: 0}
	queue = deque([node])

	while queue:
		current = queue.popleft()
		for parent in _parents_for_node(current, ontology):
			if parent in distances:
				continue
			distances[parent] = distances[current] + 1
			queue.append(parent)

	return distances


def _parents_for_node(node, ontology):
	return set(ontology.parents.get(node, set())) | set(GO_PARENTS.get(node, set()))
