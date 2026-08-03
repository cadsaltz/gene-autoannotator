from pathlib import Path

from goresolve.aliases import CATEGORY_ALIASES
from goresolve.ontology import load_go_ontology
from goresolve.retrieve import build_queries, exact_and_alias_candidates

FIXTURE = Path('tests/fixtures/go/mini.obo')


def test_build_queries_from_function_and_categories():
    queries = build_queries(
        function='involved in mitotic spindle assembling',
        functional_category=['Mitosis', 'Cytokinesis', ''],
    )
    assert queries == (
        'Mitosis',
        'Cytokinesis',
        'involved in mitotic spindle assembling',
    )


def test_exact_name_hit():
    onto = load_go_ontology(FIXTURE)
    hits = exact_and_alias_candidates(onto, ['cytokinesis'])
    assert any(h.id == 'GO:0000910' and h.source == 'exact' for h in hits)


def test_alias_hit_for_protein_synthesis_style_label():
    onto = load_go_ontology(FIXTURE)
    # alias map should include a project alias; for mini fixture also rely on synonym
    hits = exact_and_alias_candidates(onto, ['protein synthesis'])
    assert any(h.id == 'GO:0006412' for h in hits)


def test_translation_alias_includes_regulation_companion():
    assert 'GO:0006417' in CATEGORY_ALIASES['translation']


def test_translation_query_yields_exact_and_regulation_alias():
    onto = load_go_ontology(FIXTURE)
    hits = exact_and_alias_candidates(onto, ['translation'])
    by_id = {h.id: h for h in hits}
    assert by_id['GO:0006412'].source == 'exact'
    assert by_id['GO:0006417'].source == 'alias'
