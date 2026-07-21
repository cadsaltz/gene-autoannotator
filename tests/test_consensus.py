from autoannotation import organisms
from autoannotation.consensus import (
    DEFAULT_FIELD_SPECS,
    agreement_threshold,
    apply_fuzzy_deterministic_strings,
    deterministic_section_consensus,
    filter_llm_eligible_fields,
    hybrid_section_consensus,
    token_jaccard,
    validate_llm_batch_result,
    FieldSpec,
    field_specs_from_profile,
)


def test_field_specs_from_profile_includes_identity_and_llm_fields():
    profile = organisms.resolve_profile('mtb-h37rv')
    specs = field_specs_from_profile(field_defs_profile=profile)
    keys = [spec.key for spec in specs]
    assert keys[:2] == ['gene_id', 'name']
    assert specs[0].kind == 'identity'
    assert specs[1].kind == 'identity'
    assert 'function' in keys
    assert 'functional_category' in keys
    assert 'drug_susc_impact' in keys
    assert 'infection_impact' in keys
    # mtb-h37rv no longer includes essential_* in its active annotation field set.
    assert 'essential_in_vitro' not in keys
    function_spec = next(spec for spec in specs if spec.key == 'function')
    assert function_spec.kind == 'string'
    category_spec = next(spec for spec in specs if spec.key == 'functional_category')
    assert category_spec.kind == 'array'


CANDIDATE_A = {
    'gene_id': 'Rv0001', 'name': 'dnaA', 'function': 'Initiates DNA replication.',
    'functional_category': ['DNA replication/repair'], 'drug_susc_impact': None,
    'infection_impact': None, 'essential_in_vitro': True, 'essential_in_vivo': None,
}
CANDIDATE_B = {
    'gene_id': 'Rv0001', 'name': 'dnaA', 'function': 'DNA replication initiator.',
    'functional_category': ['DNA replication'], 'drug_susc_impact': None,
    'infection_impact': None, 'essential_in_vitro': None, 'essential_in_vivo': None,
}
CANDIDATE_C = {
    'gene_id': 'Rv0001', 'name': 'dnaA', 'function': 'Essential replication factor.',
    'functional_category': None, 'drug_susc_impact': None,
    'infection_impact': None, 'essential_in_vitro': True, 'essential_in_vivo': None,
}


def test_agreement_threshold_is_ceil_half():
    assert agreement_threshold(2) == 1
    assert agreement_threshold(3) == 2
    assert agreement_threshold(4) == 2
    assert agreement_threshold(5) == 3
    assert agreement_threshold(6) == 3


def test_deterministic_lone_non_null_rejected_with_three_extractors():
    lone = [{**CANDIDATE_A, 'drug_susc_impact': 'Confers rifampicin resistance.'}, CANDIDATE_B, CANDIDATE_C]
    merged, provenance, unresolved = deterministic_section_consensus(
        lone,
        expected_gene_id='Rv0001',
        expected_name='dnaA',
        fields=DEFAULT_FIELD_SPECS,
    )
    assert merged['drug_susc_impact'] is None
    assert provenance['drug_susc_impact'] == 'lone_non_null_rejected'
    assert 'drug_susc_impact' not in unresolved


def test_deterministic_lone_non_null_accepted_with_two_extractors():
    lone = [
        {**CANDIDATE_A, 'drug_susc_impact': 'Confers rifampicin resistance.'},
        {**CANDIDATE_B, 'drug_susc_impact': None},
    ]
    merged, provenance, unresolved = deterministic_section_consensus(
        lone,
        expected_gene_id='Rv0001',
        expected_name='dnaA',
        fields=DEFAULT_FIELD_SPECS,
    )
    assert merged['drug_susc_impact'] == 'Confers rifampicin resistance.'
    assert provenance['drug_susc_impact'] == 'lone_non_null_accepted'
    assert 'drug_susc_impact' not in unresolved


def test_deterministic_boolean_majority():
    merged, provenance, unresolved = deterministic_section_consensus(
        [CANDIDATE_A, CANDIDATE_B, CANDIDATE_C],
        expected_gene_id='Rv0001',
        expected_name='dnaA',
        fields=DEFAULT_FIELD_SPECS,
    )
    assert merged['essential_in_vitro'] is True
    assert provenance['essential_in_vitro'].endswith('_true')


def test_deterministic_exact_string_match():
    same = [
        {**CANDIDATE_A, 'function': 'Same function text.'},
        {**CANDIDATE_B, 'function': 'Same function text.'},
        {**CANDIDATE_C, 'function': 'Different.'},
    ]
    merged, provenance, unresolved = deterministic_section_consensus(
        same,
        expected_gene_id='Rv0001',
        expected_name='dnaA',
        fields=DEFAULT_FIELD_SPECS,
    )
    assert merged['function'] == 'Same function text.'
    assert 'function' not in unresolved


def test_deterministic_paraphrase_marks_unresolved():
    merged, provenance, unresolved = deterministic_section_consensus(
        [CANDIDATE_A, CANDIDATE_B, CANDIDATE_C],
        expected_gene_id='Rv0001',
        expected_name='dnaA',
        fields=DEFAULT_FIELD_SPECS,
    )
    assert merged['function'] is None
    assert provenance['function'] == 'insufficient_exact_agreement'
    assert 'function' in unresolved


def test_token_jaccard_unrelated_strings_are_low():
    assert token_jaccard('Used as a cloning control.', 'Required for cell wall synthesis.') < 0.35


def test_token_jaccard_paraphrases_are_higher():
    a = 'Initiates chromosomal DNA replication at oriC.'
    b = 'DNA replication initiator; oriC binding protein.'
    assert token_jaccard(a, b) >= 0.35


def test_filter_llm_eligible_rejects_unrelated_function_claims():
    candidates = [
        {'function': 'Used as a cloning control.'},
        {'function': 'Required for cell wall synthesis.'},
        {'function': 'Binds oriC and initiates DNA replication.'},
    ]
    assert filter_llm_eligible_fields(
        candidates, unresolved=['function'], fields=DEFAULT_FIELD_SPECS,
    ) == []


def test_filter_llm_eligible_allows_paraphrase_function():
    candidates = [
        {'function': 'Initiates chromosomal DNA replication at oriC.'},
        {'function': 'DNA replication initiator; oriC binding protein.'},
        {'function': 'Essential DNA replication factor acting at the origin.'},
    ]
    assert filter_llm_eligible_fields(
        candidates, unresolved=['function'], fields=DEFAULT_FIELD_SPECS,
    ) == ['function']


def test_fuzzy_deterministic_accepts_near_duplicate_strings():
    merged = {'function': None}
    provenance = {'function': 'insufficient_exact_agreement'}
    candidates = [
        {'function': 'Initiates DNA replication at oriC.'},
        {'function': 'Initiates DNA replication at oriC'},
    ]
    updated, updated_prov, still_unresolved = apply_fuzzy_deterministic_strings(
        merged, provenance, candidates, unresolved=['function'], fields=DEFAULT_FIELD_SPECS,
    )
    assert updated['function'] == 'Initiates DNA replication at oriC.'
    assert still_unresolved == []


def test_validate_rejects_merge_not_traceable_to_candidates():
    candidates = [
        {'function': 'Initiates DNA replication at oriC.'},
        {'function': 'DNA replication initiator.'},
    ]
    result = validate_llm_batch_result(
        {'function': 'Used as a cloning control.'},
        excerpt=None,
        candidates=candidates,
        field_keys=['function'],
        fields=DEFAULT_FIELD_SPECS,
    )
    assert result['function'] is None


def test_validate_accepts_candidate_traceable_merge_without_excerpt():
    candidates = [
        {'function': 'Initiates chromosomal DNA replication at oriC.'},
        {'function': 'DNA replication initiator; oriC binding protein.'},
    ]
    merged_text = 'Initiates DNA replication at oriC.'
    result = validate_llm_batch_result(
        {'function': merged_text},
        excerpt=None,
        candidates=candidates,
        field_keys=['function'],
        fields=DEFAULT_FIELD_SPECS,
    )
    assert result['function'] == merged_text


def test_validate_excerpt_overlap_rejects_when_provided_and_no_support():
    excerpt = 'Deletion of dnaA abolished growth in rich medium.'
    candidates = [
        {'function': 'Initiates DNA replication at oriC.'},
        {'function': 'DNA replication initiator at oriC.'},
    ]
    merged_text = 'Initiates DNA replication at oriC.'
    result = validate_llm_batch_result(
        {'function': merged_text},
        excerpt=excerpt,
        candidates=candidates,
        field_keys=['function'],
        fields=DEFAULT_FIELD_SPECS,
    )
    assert result['function'] is None


def test_validate_accepts_when_traceable_and_excerpt_overlaps():
    excerpt = (
        'DnaA binds the chromosomal origin (oriC) and initiates DNA replication. '
        'Deletion abolished growth.'
    )
    candidates = [
        {'function': 'Initiates chromosomal DNA replication at oriC.'},
        {'function': 'DNA replication initiator; oriC binding protein.'},
    ]
    merged_text = 'Initiates DNA replication at oriC.'
    result = validate_llm_batch_result(
        {'function': merged_text},
        excerpt=excerpt,
        candidates=candidates,
        field_keys=['function'],
        fields=DEFAULT_FIELD_SPECS,
    )
    assert result['function'] == merged_text


def test_hybrid_skips_llm_when_rules_resolve_everything():
    unanimous = [
        {**CANDIDATE_A, 'function': 'Same text.', 'functional_category': ['DNA replication/repair']},
        {**CANDIDATE_B, 'function': 'Same text.', 'functional_category': ['DNA replication/repair']},
    ]

    def fail_if_called(*args, **kwargs):
        raise AssertionError('batch merger should not be called')

    merged, provenance, llm_calls = hybrid_section_consensus(
        unanimous,
        excerpt='Same text.',
        expected_gene_id='Rv0001',
        expected_name='dnaA',
        batch_merger=fail_if_called,
    )
    assert llm_calls == 0
    assert merged['function'] == 'Same text.'


def test_hybrid_nulls_semantic_conflict_without_llm():
    candidates = [
        {**CANDIDATE_A, 'function': 'Used as a cloning control.', 'functional_category': ['cloning']},
        {**CANDIDATE_B, 'function': 'Required for cell wall synthesis.', 'functional_category': ['cell wall']},
    ]

    def counting_merger(normalized, unresolved_fields):
        raise AssertionError('batch merger should not be called')

    merged, provenance, llm_calls = hybrid_section_consensus(
        candidates,
        excerpt='Binds oriC and initiates DNA replication.',
        expected_gene_id='Rv0001',
        expected_name='dnaA',
        batch_merger=counting_merger,
    )
    assert llm_calls == 0
    assert merged['function'] is None
    assert provenance['function'] == 'semantic_conflict'


def test_hybrid_invokes_batch_merger_once_for_paraphrase():
    calls = {'count': 0, 'fields': None}

    def fake_merger(normalized, unresolved_fields):
        calls['count'] += 1
        calls['fields'] = list(unresolved_fields)
        return {
            'function': 'Initiates DNA replication at oriC.',
            'functional_category': ['DNA replication'],
        }

    excerpt = (
        'DnaA binds the chromosomal origin (oriC) and initiates DNA replication. '
        'Deletion abolished growth.'
    )
    merged, provenance, llm_calls = hybrid_section_consensus(
        [CANDIDATE_A, CANDIDATE_B],
        excerpt=excerpt,
        expected_gene_id='Rv0001',
        expected_name='dnaA',
        batch_merger=fake_merger,
    )
    assert llm_calls == 1
    assert calls['count'] == 1
    assert 'function' in calls['fields']
    assert merged['function'] is not None
    assert provenance['function'] == 'llm_batch_merge'


def test_regression_edge_function_three_unrelated_claims_null_without_llm():
    candidates = [
        {'gene_id': 'Rv0001', 'name': 'dnaA', 'function': 'Used as a cloning control.',
         'functional_category': ['cloning'], 'drug_susc_impact': None, 'infection_impact': None,
         'essential_in_vitro': None, 'essential_in_vivo': None},
        {'gene_id': 'Rv0001', 'name': 'dnaA', 'function': 'Required for cell wall synthesis.',
         'functional_category': ['cell wall'], 'drug_susc_impact': None, 'infection_impact': None,
         'essential_in_vitro': None, 'essential_in_vivo': None},
    ]
    merged, provenance, llm_calls = hybrid_section_consensus(
        candidates,
        excerpt='Binds oriC and initiates DNA replication.',
        expected_gene_id='Rv0001',
        expected_name='dnaA',
        batch_merger=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('no LLM')),
    )
    assert llm_calls == 0
    assert merged['function'] is None
    assert provenance['function'] == 'semantic_conflict'


def test_regression_lone_drug_claim_accepted_with_two_extractors():
    candidates = [
        {**CANDIDATE_A, 'drug_susc_impact': 'Confers rifampicin resistance.'},
        {**CANDIDATE_B, 'drug_susc_impact': None},
    ]
    merged, provenance, llm_calls = hybrid_section_consensus(
        candidates,
        excerpt='No drug data in this excerpt.',
        expected_gene_id='Rv0001',
        expected_name='dnaA',
        batch_merger=None,
    )
    assert llm_calls == 0
    assert merged['drug_susc_impact'] == 'Confers rifampicin resistance.'
    assert provenance['drug_susc_impact'] == 'lone_non_null_accepted'


def test_four_extractor_majority_requires_two_matching():
    """ceil(4/2)=2: two identical non-nulls beat two nulls."""
    candidates = [
        {**CANDIDATE_A, 'drug_susc_impact': 'Confers rifampicin resistance.'},
        {**CANDIDATE_B, 'drug_susc_impact': 'Confers rifampicin resistance.'},
        {**CANDIDATE_C, 'drug_susc_impact': None},
        {**CANDIDATE_A, 'drug_susc_impact': None, 'essential_in_vitro': None},
    ]
    merged, provenance, unresolved = deterministic_section_consensus(
        candidates,
        expected_gene_id='Rv0001',
        expected_name='dnaA',
        fields=DEFAULT_FIELD_SPECS,
    )
    assert merged['drug_susc_impact'] == 'Confers rifampicin resistance.'
    assert provenance['drug_susc_impact'].endswith('_exact')
