from pathlib import Path
from goresolve.ontology import load_go_ontology

FIXTURE = Path('tests/fixtures/go/mini.obo')


def test_load_mini_obo_indexes_names_and_skips_obsolete():
    onto = load_go_ontology(FIXTURE)
    assert 'GO:0000910' in onto.terms
    assert 'GO:9999999' not in onto.terms
    assert 'cytokinesis' in onto.label_index
    assert 'GO:0000910' in onto.label_index['cytokinesis']
    assert 'protein synthesis' in onto.label_index
    assert 'GO:0006412' in onto.label_index['protein synthesis']
    assert onto.parents['GO:0000278'] == {'GO:0007049'}


def test_document_text_includes_name_synonym_definition():
    onto = load_go_ontology(FIXTURE)
    doc = onto.document_text('GO:0006412')
    assert 'translation' in doc.lower()
    assert 'protein synthesis' in doc.lower()
