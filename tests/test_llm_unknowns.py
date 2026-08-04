import json

from autoannotation import llms
from autoannotation import metadata


def test_is_unknown_value_treats_null_empty_and_placeholders():
    assert llms.is_unknown_value(None)
    assert llms.is_unknown_value('')
    assert llms.is_unknown_value('unknown')
    assert llms.is_unknown_value([])
    assert not llms.is_unknown_value('DNA replication initiator')
    assert not llms.is_unknown_value(['virulence'])


def test_normalize_annotation_fields_maps_placeholders_to_null():
    raw = {
        'rv_id': 'Rv0001',
        'name': 'dnaA',
        'function': 'Initiates replication.',
        'functional_category': [],
        'drug_susc_impact': 'n/a',
        'infection_impact': '',
        'essential_in_vitro': None,
        'essential_in_vivo': True,
    }

    normalized = llms.normalize_annotation_fields(raw)

    assert normalized['function'] == 'Initiates replication.'
    assert normalized['functional_category'] is None
    assert normalized['drug_susc_impact'] is None
    assert normalized['infection_impact'] is None
    assert normalized['essential_in_vitro'] is None
    assert normalized['essential_in_vivo'] is True


def test_json_regex_filter_accepts_partial_section_json():
    section_json = json.dumps({
        'rv_id': 'Rv0001',
        'name': 'dnaA',
        'function': 'Binds oriC.',
        'drug_susc_impact': None,
    })

    assert llms.LlmHandler.json_regex_filter(section_json)


def test_build_field_coverage_marks_null_as_insufficient():
    coverage = metadata.build_field_coverage({
        'function': 'Known function.',
        'functional_category': ['DNA replication'],
        'drug_susc_impact': None,
        'infection_impact': None,
        'essential_in_vitro': None,
        'essential_in_vivo': True,
    })

    assert coverage['function'] == 'supported'
    assert coverage['drug_susc_impact'] == 'insufficient_evidence'
    assert coverage['essential_in_vivo'] == 'supported'
