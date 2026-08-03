from goresolve.query_clean import clean_query_text
from goresolve.retrieve import build_queries


def test_clean_strips_pmid_and_pmc_citations():
    raw = 'heavy metal efflux (PMID 21925112)'
    assert clean_query_text(raw) == 'heavy metal efflux'
    raw2 = 'GroES overexpression during hypoxia (PMC5017210).'
    assert 'PMC' not in clean_query_text(raw2)
    assert 'PMID' not in clean_query_text(raw2)


def test_clean_strips_inline_pmid_colon_forms():
    assert clean_query_text('copper transport PMID: 28536560') == 'copper transport'


def test_build_queries_applies_cleaning_and_drops_empty():
    queries = build_queries(
        function='does a thing (PMID 1)',
        functional_category=['mRNA stability (PMID 38270449)', '  ', '(PMID 999)'],
    )
    assert queries == ('mRNA stability', 'does a thing')


def test_build_queries_caps_categories_but_keeps_function():
    cats = [f'cat{i}' for i in range(12)]
    queries = build_queries('function text here', cats, max_categories=8)
    assert queries[:8] == tuple(f'cat{i}' for i in range(8))
    assert queries[-1] == 'function text here'
    assert len(queries) == 9
