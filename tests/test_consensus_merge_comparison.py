"""Compare two consensus design ideas on realistic and edge scenarios.

Design A (rules_only):
  Deterministic merge. 2-of-3 exact match for strings. Lone non-null → null. No LLM.

Design B (rules_plus_llm):
  Same rules for booleans/identity/lone-null. ONE batched LLM call for all
  unresolved string/array fields (production-shaped).

Run with full printed input/output comparison (simulated batch LLM):
    pytest tests/test_consensus_merge_comparison.py -s -v -k design_comparison

Run ALL scenarios with live qwen3:8b batch merge (recommended on server):
    ollama pull qwen3:8b
    pytest tests/test_consensus_merge_comparison.py -s -v -k live_all_scenarios

Optional: compare batch vs per-field LLM strategies:
    pytest tests/test_consensus_merge_comparison.py -s -v -k batch_vs_per_field

Override model:
    CONSENSUS_TEST_MODEL=qwen3:8b pytest tests/test_consensus_merge_comparison.py -s -v -k live
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from tests.consensus_merge_prototypes import (
    OLLAMA_CONSENSUS_MODEL,
    conservative_batch_llm_simulator,
    deterministic_consensus,
    format_scenario_report,
    generative_batch_llm_simulator,
    hybrid_consensus_batch,
    hybrid_consensus_per_field,
    ollama_batch_merger,
)


@dataclass(frozen=True)
class Scenario:
    name: str
    excerpt: str
    expected_gene_id: str
    expected_name: str
    candidates: list[dict]
    notes: str


def _run_and_print(
    scenario: Scenario,
    *,
    design_b_backend: str,
    batch_merger=conservative_batch_llm_simulator,
    use_per_field: bool = False,
):
    design_a, design_a_meta = deterministic_consensus(
        scenario.candidates,
        excerpt=scenario.excerpt,
        expected_gene_id=scenario.expected_gene_id,
        expected_name=scenario.expected_name,
    )
    if use_per_field:
        design_b, design_b_meta, llm_calls = hybrid_consensus_per_field(
            scenario.candidates,
            excerpt=scenario.excerpt,
            expected_gene_id=scenario.expected_gene_id,
            expected_name=scenario.expected_name,
        )
    else:
        design_b, design_b_meta, llm_calls = hybrid_consensus_batch(
            scenario.candidates,
            excerpt=scenario.excerpt,
            expected_gene_id=scenario.expected_gene_id,
            expected_name=scenario.expected_name,
            batch_merger=batch_merger,
        )
    unresolved_fields = [
        key for key, reason in design_b_meta.items()
        if reason in {'llm_batch_merge', 'llm_batch_null', 'llm_string_merge', 'llm_string_null', 'llm_array_merge', 'llm_array_null'}
    ]
    report = format_scenario_report(
        scenario.name,
        excerpt=scenario.excerpt,
        candidates=scenario.candidates,
        design_a=design_a,
        design_a_meta=design_a_meta,
        design_b=design_b,
        design_b_meta=design_b_meta,
        design_b_backend=design_b_backend,
        notes=scenario.notes,
        llm_calls=llm_calls,
        unresolved_fields=unresolved_fields,
    )
    print(report)
    return design_a, design_a_meta, design_b, design_b_meta, llm_calls


SCENARIOS = [
    Scenario(
        name='realistic_dnaA_results_paraphrase',
        excerpt=(
            'Deletion of dnaA (Rv0001) in Mycobacterium tuberculosis H37Rv abolished growth '
            'in rich medium, indicating the gene is essential for viability in vitro. '
            'DnaA binds the chromosomal origin (oriC) and initiates DNA replication.'
        ),
        expected_gene_id='Rv0001',
        expected_name='dnaA',
        candidates=[
            {
                'gene_id': 'Rv0001',
                'name': 'dnaA',
                'function': 'Initiates chromosomal DNA replication at oriC.',
                'functional_category': ['DNA replication/repair'],
                'drug_susc_impact': None,
                'infection_impact': None,
                'essential_in_vitro': True,
                'essential_in_vivo': None,
            },
            {
                'gene_id': 'Rv0001',
                'name': 'dnaA',
                'function': 'DNA replication initiator that binds oriC.',
                'functional_category': ['DNA replication'],
                'drug_susc_impact': None,
                'infection_impact': None,
                'essential_in_vitro': None,
                'essential_in_vivo': None,
            },
            {
                'gene_id': 'Rv0001',
                'name': 'dnaA',
                'function': 'Required for initiation of DNA replication.',
                'functional_category': ['DNA replication/repair', 'cell cycle'],
                'drug_susc_impact': None,
                'infection_impact': None,
                'essential_in_vitro': True,
                'essential_in_vivo': None,
            },
        ],
        notes=(
            'Classic extraction disagreement: three paraphrased function strings, partial category overlap, '
            '2/3 essential_in_vitro agreement.'
        ),
    ),
    Scenario(
        name='realistic_lone_essentiality_hallucination',
        excerpt=(
            'The dnaA gene product was purified and shown to bind oriC in vitro. '
            'No transposon or deletion phenotype was reported in this study.'
        ),
        expected_gene_id='Rv0001',
        expected_name='dnaA',
        candidates=[
            {
                'gene_id': 'Rv0001',
                'name': 'dnaA',
                'function': 'Binds oriC and initiates DNA replication.',
                'functional_category': ['DNA replication/repair'],
                'drug_susc_impact': None,
                'infection_impact': None,
                'essential_in_vitro': True,
                'essential_in_vivo': None,
            },
            {
                'gene_id': 'Rv0001',
                'name': 'dnaA',
                'function': 'Origin-binding replication initiator.',
                'functional_category': ['DNA replication/repair'],
                'drug_susc_impact': None,
                'infection_impact': None,
                'essential_in_vitro': None,
                'essential_in_vivo': None,
            },
            {
                'gene_id': 'Rv0001',
                'name': 'dnaA',
                'function': 'Binds the chromosomal origin of replication.',
                'functional_category': None,
                'drug_susc_impact': None,
                'infection_impact': None,
                'essential_in_vitro': None,
                'essential_in_vivo': None,
            },
        ],
        notes='One model hallucinates essentiality from gene class; excerpt does not support it.',
    ),
    Scenario(
        name='realistic_drug_resistance_lone_claim',
        excerpt=(
            'Rv3407 transposon mutants showed increased susceptibility to isoniazid in vitro. '
            'Complementation restored the wild-type MIC.'
        ),
        expected_gene_id='Rv3407',
        expected_name='Rv3407',
        candidates=[
            {
                'gene_id': 'Rv3407',
                'name': 'Rv3407',
                'function': None,
                'functional_category': None,
                'drug_susc_impact': 'Transposon disruption increases isoniazid susceptibility.',
                'infection_impact': None,
                'essential_in_vitro': None,
                'essential_in_vivo': None,
            },
            {
                'gene_id': 'Rv3407',
                'name': 'Rv3407',
                'function': None,
                'functional_category': None,
                'drug_susc_impact': None,
                'infection_impact': None,
                'essential_in_vitro': None,
                'essential_in_vivo': None,
            },
            {
                'gene_id': 'Rv3407',
                'name': 'Rv3407',
                'function': None,
                'functional_category': None,
                'drug_susc_impact': None,
                'infection_impact': None,
                'essential_in_vitro': None,
                'essential_in_vivo': None,
            },
        ],
        notes='Only one model extracts drug impact. Deterministic and hybrid should reject lone claim.',
    ),
    Scenario(
        name='realistic_unanimous_abstract',
        excerpt=(
            'Rv1813 encodes a conserved membrane protein implicated in hypoxic persistence '
            'of Mycobacterium tuberculosis.'
        ),
        expected_gene_id='Rv1813',
        expected_name='Rv1813',
        candidates=[
            {
                'gene_id': 'Rv1813',
                'name': 'Rv1813',
                'function': 'Conserved membrane protein implicated in hypoxic persistence.',
                'functional_category': ['persistence'],
                'drug_susc_impact': None,
                'infection_impact': None,
                'essential_in_vitro': None,
                'essential_in_vivo': None,
            },
            {
                'gene_id': 'Rv1813',
                'name': 'Rv1813',
                'function': 'Conserved membrane protein implicated in hypoxic persistence.',
                'functional_category': ['persistence'],
                'drug_susc_impact': None,
                'infection_impact': None,
                'essential_in_vitro': None,
                'essential_in_vivo': None,
            },
            {
                'gene_id': 'Rv1813',
                'name': 'Rv1813',
                'function': 'Conserved membrane protein implicated in hypoxic persistence.',
                'functional_category': ['persistence'],
                'drug_susc_impact': None,
                'infection_impact': None,
                'essential_in_vitro': None,
                'essential_in_vivo': None,
            },
        ],
        notes='All models agree exactly. Neither design should invoke an LLM merge.',
    ),
    Scenario(
        name='random_placeholder_and_empty_strings',
        excerpt='No phenotype was measured for Rv0001 in this study.',
        expected_gene_id='Rv0001',
        expected_name='dnaA',
        candidates=[
            {
                'gene_id': 'Rv0001',
                'name': 'dnaA',
                'function': 'unknown',
                'functional_category': [],
                'drug_susc_impact': 'n/a',
                'infection_impact': '',
                'essential_in_vitro': None,
                'essential_in_vivo': 'not reported',
            },
            {
                'gene_id': 'Rv0001',
                'name': 'dnaA',
                'function': None,
                'functional_category': None,
                'drug_susc_impact': None,
                'infection_impact': None,
                'essential_in_vitro': None,
                'essential_in_vivo': None,
            },
            {
                'gene_id': 'Rv0001',
                'name': 'dnaA',
                'function': 'Not characterized in this study.',
                'functional_category': ['unknown'],
                'drug_susc_impact': None,
                'infection_impact': None,
                'essential_in_vitro': None,
                'essential_in_vivo': None,
            },
        ],
        notes='Messy extractor outputs with placeholders should normalize to nulls, not merge junk.',
    ),
    Scenario(
        name='unlikely_wrong_gene_hallucination',
        excerpt='CRISPRi of Rv0001 reduced growth in vitro by 90% after 7 days.',
        expected_gene_id='Rv0001',
        expected_name='dnaA',
        candidates=[
            {
                'gene_id': 'Rv0001',
                'name': 'dnaA',
                'function': 'CRISPRi knockdown reduces viability in vitro.',
                'functional_category': ['essentiality'],
                'drug_susc_impact': None,
                'infection_impact': None,
                'essential_in_vitro': True,
                'essential_in_vivo': None,
            },
            {
                'gene_id': 'Rv0002',
                'name': 'Rv0002',
                'function': 'CRISPRi knockdown reduces viability in vitro.',
                'functional_category': ['essentiality'],
                'drug_susc_impact': None,
                'infection_impact': None,
                'essential_in_vitro': True,
                'essential_in_vivo': None,
            },
            {
                'gene_id': 'Rv0001',
                'name': 'dnaA',
                'function': 'CRISPRi knockdown reduces viability in vitro.',
                'functional_category': ['essentiality'],
                'drug_susc_impact': None,
                'infection_impact': None,
                'essential_in_vitro': True,
                'essential_in_vivo': None,
            },
        ],
        notes='Middle candidate uses wrong locus in JSON; production filter would reject it later.',
    ),
    Scenario(
        name='edge_boolean_true_false_conflict',
        excerpt='Transposon insertion in Rv0018c was lethal in vitro but a conditional allele grew in mice.',
        expected_gene_id='Rv0018c',
        expected_name='Rv0018c',
        candidates=[
            {
                'gene_id': 'Rv0018c',
                'name': 'Rv0018c',
                'function': None,
                'functional_category': None,
                'drug_susc_impact': None,
                'infection_impact': None,
                'essential_in_vitro': True,
                'essential_in_vivo': False,
            },
            {
                'gene_id': 'Rv0018c',
                'name': 'Rv0018c',
                'function': None,
                'functional_category': None,
                'drug_susc_impact': None,
                'infection_impact': None,
                'essential_in_vitro': True,
                'essential_in_vivo': None,
            },
            {
                'gene_id': 'Rv0018c',
                'name': 'Rv0018c',
                'function': None,
                'functional_category': None,
                'drug_susc_impact': None,
                'infection_impact': None,
                'essential_in_vitro': False,
                'essential_in_vivo': None,
            },
        ],
        notes='Boolean conflict on essential_in_vitro should resolve to null in both designs.',
    ),
    Scenario(
        name='edge_infection_two_similar_one_extra_detail',
        excerpt='An Rv3678c deletion mutant showed a 2-log reduction in bacterial load in mouse lungs.',
        expected_gene_id='Rv3678c',
        expected_name='Rv3678c',
        candidates=[
            {
                'gene_id': 'Rv3678c',
                'name': 'Rv3678c',
                'function': None,
                'functional_category': None,
                'drug_susc_impact': None,
                'infection_impact': 'Deletion reduces bacterial load in mouse lungs.',
                'essential_in_vitro': None,
                'essential_in_vivo': None,
            },
            {
                'gene_id': 'Rv3678c',
                'name': 'Rv3678c',
                'function': None,
                'functional_category': None,
                'drug_susc_impact': None,
                'infection_impact': 'Deletion attenuates infection in a mouse model.',
                'essential_in_vitro': None,
                'essential_in_vivo': None,
            },
            {
                'gene_id': 'Rv3678c',
                'name': 'Rv3678c',
                'function': None,
                'functional_category': None,
                'drug_susc_impact': None,
                'infection_impact': None,
                'essential_in_vitro': None,
                'essential_in_vivo': None,
            },
        ],
        notes='Two non-null paraphrases + one null. Hybrid LLM can merge; deterministic cannot.',
    ),
    Scenario(
        name='edge_function_three_unrelated_claims',
        excerpt='Rv0001 was used only as a cloning vector control in this study.',
        expected_gene_id='Rv0001',
        expected_name='dnaA',
        candidates=[
            {
                'gene_id': 'Rv0001',
                'name': 'dnaA',
                'function': 'Used as a cloning control.',
                'functional_category': ['cloning'],
                'drug_susc_impact': None,
                'infection_impact': None,
                'essential_in_vitro': None,
                'essential_in_vivo': None,
            },
            {
                'gene_id': 'Rv0001',
                'name': 'dnaA',
                'function': 'Required for cell wall synthesis.',
                'functional_category': ['cell wall'],
                'drug_susc_impact': None,
                'infection_impact': None,
                'essential_in_vitro': None,
                'essential_in_vivo': None,
            },
            {
                'gene_id': 'Rv0001',
                'name': 'dnaA',
                'function': 'Regulates virulence gene expression.',
                'functional_category': ['virulence'],
                'drug_susc_impact': None,
                'infection_impact': None,
                'essential_in_vitro': None,
                'essential_in_vivo': None,
            },
        ],
        notes='Three incompatible functions from sloppy extractors; both designs should avoid inventing a combo.',
    ),
    Scenario(
        name='extremely_unlikely_all_models_invent_phenotypes',
        excerpt='We thank the reviewers for helpful comments. No experiments on Rv0001 were performed.',
        expected_gene_id='Rv0001',
        expected_name='dnaA',
        candidates=[
            {
                'gene_id': 'Rv0001',
                'name': 'dnaA',
                'function': 'Essential for biofilm formation in macrophages.',
                'functional_category': ['virulence', 'biofilm'],
                'drug_susc_impact': 'Confers rifampicin resistance.',
                'infection_impact': 'Required for persistence in mice.',
                'essential_in_vitro': True,
                'essential_in_vivo': True,
            },
            {
                'gene_id': 'Rv0001',
                'name': 'dnaA',
                'function': 'Catalyzes cell wall arabinogalactan branching.',
                'functional_category': ['cell wall'],
                'drug_susc_impact': 'Increases ethambutol susceptibility.',
                'infection_impact': None,
                'essential_in_vitro': False,
                'essential_in_vivo': True,
            },
            {
                'gene_id': 'Rv0001',
                'name': 'dnaA',
                'function': 'RNA polymerase sigma factor.',
                'functional_category': ['transcription'],
                'drug_susc_impact': None,
                'infection_impact': 'Attenuated in guinea pig model.',
                'essential_in_vitro': True,
                'essential_in_vivo': None,
            },
        ],
        notes='Acknowledgments-only excerpt with rich hallucinations from all models.',
    ),
]


@pytest.mark.parametrize('scenario', SCENARIOS, ids=[s.name for s in SCENARIOS])
def test_design_comparison_simulated_batch_llm(scenario: Scenario):
    """Design A vs Design B using one batched simulated LLM call (production-shaped)."""
    design_a, _, design_b, _, llm_calls = _run_and_print(
        scenario,
        design_b_backend='simulator batch (conservative, 1 call)',
    )
    assert design_a['gene_id'] == scenario.expected_gene_id
    assert design_b['gene_id'] == scenario.expected_gene_id
    assert llm_calls in (0, 1)


def test_lone_non_null_boolean_both_designs_reject():
    scenario = next(s for s in SCENARIOS if s.name == 'realistic_lone_essentiality_hallucination')
    design_a, _, design_b, _, _ = _run_and_print(
        scenario,
        design_b_backend='simulator batch (conservative, 1 call)',
    )
    assert design_a['essential_in_vitro'] is None
    assert design_b['essential_in_vitro'] is None


def test_unanimous_exact_never_needs_llm_merge():
    scenario = next(s for s in SCENARIOS if s.name == 'realistic_unanimous_abstract')
    _, design_a_meta, _, design_b_meta, _ = _run_and_print(
        scenario,
        design_b_backend='simulator batch (conservative, 1 call)',
    )
    assert design_a_meta['function'] == '3/3_exact'
    assert design_b_meta['function'] == '3/3_exact'
    assert 'llm_' not in design_b_meta['function']


def test_paraphrase_function_rules_only_null_llm_merged():
    scenario = next(s for s in SCENARIOS if s.name == 'realistic_dnaA_results_paraphrase')
    design_a, _, design_b, design_b_meta, _ = _run_and_print(
        scenario,
        design_b_backend='simulator batch (conservative, 1 call)',
    )
    assert design_a['function'] is None
    assert design_b['function'] is not None
    assert design_b_meta['function'] in {'llm_batch_merge', 'llm_string_merge'}


def test_generative_llm_simulator_is_more_permissive_than_conservative():
    scenario = next(s for s in SCENARIOS if s.name == 'realistic_dnaA_results_paraphrase')
    _, _, conservative, _, _ = _run_and_print(
        scenario,
        design_b_backend='simulator batch (conservative, 1 call)',
    )
    _, _, generative, generative_meta, _ = _run_and_print(
        scenario,
        design_b_backend='simulator batch (generative — shows merge risk)',
        batch_merger=generative_batch_llm_simulator,
    )
    assert conservative['functional_category'] is not None
    assert generative['functional_category'] is not None
    assert len(generative['functional_category']) >= len(conservative['functional_category'])
    assert generative_meta['functional_category'] in {'llm_batch_merge', 'llm_array_merge'}


def test_acknowledgment_only_excerpt_prefers_nulls():
    scenario = next(s for s in SCENARIOS if s.name == 'extremely_unlikely_all_models_invent_phenotypes')
    design_a, _, design_b_cons, _, _ = _run_and_print(
        scenario,
        design_b_backend='simulator batch (conservative, 1 call)',
    )
    _, _, design_b_gen, _, _ = _run_and_print(
        scenario,
        design_b_backend='simulator batch (generative — shows merge risk)',
        batch_merger=generative_batch_llm_simulator,
    )
    assert design_a['drug_susc_impact'] is None
    assert design_b_cons['drug_susc_impact'] is None
    assert design_b_gen['drug_susc_impact'] is not None


def _ollama_model_available(model: str) -> bool:
    try:
        import ollama
    except ImportError:
        return False
    try:
        installed = set()
        list_result = ollama.list()
        entries = list_result.get('models', []) if isinstance(list_result, dict) else list_result.models
        for entry in entries:
            if isinstance(entry, dict):
                name = entry.get('model') or entry.get('name')
            else:
                name = getattr(entry, 'model', None) or getattr(entry, 'name', None)
            if name:
                installed.add(name)
                installed.add(name.split(':')[0])
        return model in installed or model.split(':')[0] in installed
    except Exception:
        return False


@pytest.mark.parametrize('scenario', SCENARIOS, ids=[s.name for s in SCENARIOS])
@pytest.mark.skipif(
    not _ollama_model_available(OLLAMA_CONSENSUS_MODEL),
    reason=f'Ollama model {OLLAMA_CONSENSUS_MODEL} not available — run: ollama pull {OLLAMA_CONSENSUS_MODEL}',
)
def test_live_all_scenarios_design_comparison(scenario: Scenario):
    """Design A vs Design B with live batched Ollama — primary server evaluation test."""
    _run_and_print(
        scenario,
        design_b_backend=f'live Ollama batch ({OLLAMA_CONSENSUS_MODEL}, 1 call if needed)',
        batch_merger=ollama_batch_merger,
    )


@pytest.mark.parametrize('scenario', SCENARIOS, ids=[s.name for s in SCENARIOS])
def test_batch_vs_per_field_llm_call_count(scenario: Scenario):
    """Shows why batch is the production-shaped test: same fields, fewer calls."""
    _, _, _, _, batch_calls = _run_and_print(
        scenario,
        design_b_backend='simulator batch (conservative, 1 call)',
    )
    _, _, _, _, per_field_calls = _run_and_print(
        scenario,
        design_b_backend='simulator per-field (legacy comparison)',
        use_per_field=True,
    )
    print(
        f'CALL COUNT — {scenario.name}: batch={batch_calls}, per_field={per_field_calls}'
    )
    assert batch_calls <= per_field_calls
    assert batch_calls in (0, 1)


def test_print_run_summary(capsys):
    summary = f'''
CONSENSUS DESIGN COMPARISON — HOW TO READ RESULTS
================================================

Design A (rules_only):
  - No LLM at consensus. Exact 2-of-3 for strings. Lone non-null → null.

Design B (rules_plus_llm):
  - Same rules, then ONE batched LLM call for all unresolved string/array fields.
  - Live model: {OLLAMA_CONSENSUS_MODEL} (override with CONSENSUS_TEST_MODEL)

Each scenario prints:
  1. The source excerpt
  2. All three raw candidate JSON objects (extractor outputs)
  3. Per-field: C1|C2|C3 inputs → Design A output → Design B output → verdict
  4. LLM calls made (0 or 1 batch) and which fields were unresolved
  5. SCENARIO VERDICT: whether the LLM recovered fields rules-only missed

Is the consensus LLM worth it?
  - Look at "Fields recovered by LLM that rules-only left null"
  - If empty across most scenarios → Design A is sufficient
  - If recovered fields look excerpt-supported → Design B adds real value
  - If "CONFLICT" or generative outputs appear → LLM may be introducing risk

Recommended server command:
  ollama pull {OLLAMA_CONSENSUS_MODEL}
  pytest tests/test_consensus_merge_comparison.py -s -v -k live_all_scenarios
'''
    print(summary)
    captured = capsys.readouterr()
    assert OLLAMA_CONSENSUS_MODEL in captured.out
