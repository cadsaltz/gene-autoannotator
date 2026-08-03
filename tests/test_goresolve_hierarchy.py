from pathlib import Path

from goresolve.hierarchy import drop_ancestor_terms
from goresolve.ontology import load_go_ontology


FIXTURE = Path('tests/fixtures/go/mini.obo')


def test_drops_parent_when_child_present():
    ontology = load_go_ontology(FIXTURE)

    kept = drop_ancestor_terms(
        ['GO:0007049', 'GO:0000278', 'GO:0000910'],
        ontology,
    )

    assert kept == ['GO:0000278', 'GO:0000910']


def test_keeps_unrelated_terms():
    ontology = load_go_ontology(FIXTURE)

    kept = drop_ancestor_terms(['GO:0000910', 'GO:0006412'], ontology)

    assert kept == ['GO:0000910', 'GO:0006412']
