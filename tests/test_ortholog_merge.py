import copy
import json

from autoannotation import field_defs
from autoannotation import metadata
from autoannotation import organisms
from autoannotation.metadata import (
    attach_ortholog_metadata,
    build_ortholog_pass_metadata,
    find_fields_needing_ortholog,
    merge_ortholog_evidence,
)
from autoannotation.orthology import OrthologHit


def test_find_fields_needing_ortholog_selects_missing_paper_llm_fields():
    annotation = {
        'function': None,
        'functional_category': ['DNA replication'],
        'drug_susc_impact': None,
    }
    coverage = {
        'function': 'insufficient_evidence',
        'functional_category': 'supported',
        'drug_susc_impact': 'insufficient_evidence',
    }

    missing = find_fields_needing_ortholog(
        annotation,
        coverage,
        field_defs.REQUIRED_DEFAULT_FIELDS,
    )

    assert missing == ['function']


def test_find_fields_needing_ortholog_skips_non_ortholog_allowed_fields():
    annotation = {'function': None, 'functional_category': None}
    coverage = {
        'function': 'insufficient_evidence',
        'functional_category': 'insufficient_evidence',
    }

    missing = find_fields_needing_ortholog(
        annotation,
        coverage,
        field_defs.REQUIRED_DEFAULT_FIELDS,
    )

    assert missing == ['function']


def test_find_fields_needing_ortholog_includes_functional_category_when_enabled():
    annotation = {'function': 'DNA replication', 'functional_category': None}
    coverage = {
        'function': 'supported',
        'functional_category': 'insufficient_evidence',
    }
    fields = field_defs.resolve_effective_fields(
        organisms.profile_from_mapping({
            'profile_id': 'fc-ortholog',
            'canonical_name': 'FC ortholog',
            'species_name': 'Test species',
            'kegg_organism_code': 'mtu',
            'default_field_ortholog': {'functional_category': True},
        })
    )

    missing = find_fields_needing_ortholog(annotation, coverage, fields)

    assert missing == ['functional_category']


def test_merge_ortholog_evidence_fills_null_direct_fields_only():
    direct = {
        'gene_id': 'Rv0001',
        'function': None,
        'functional_category': ['DNA replication'],
        'annotation_metadata': {'field_coverage': {'function': 'insufficient_evidence'}},
        'annotation_notes': 'Direct evidence limited.',
    }
    ortholog = {
        'gene_id': 'MO_000001',
        'function': 'Initiates DNA replication in M. orygis.',
    }
    hit = OrthologHit(
        source_organism_code='mory',
        source_organism_name='Mycobacterium orygis',
        source_gene_id='MO_000001',
        source_gene_name='dnaA',
        score=507.0,
        lookup_source='kegg_ssdb',
    )

    merged, filled = merge_ortholog_evidence(
        direct,
        ortholog,
        ['function'],
        hit,
        target_gene_id='Rv0001',
        target_gene_name='dnaA',
    )

    assert filled == ['function']
    assert merged['function'] == ortholog['function']
    assert merged['functional_category'] == ['DNA replication']
    assert merged['annotation_metadata']['field_provenance']['function'] == 'ortholog_derived'
    assert merged['annotation_metadata']['review_flags']['function'] is True
    assert 'ortholog evidence' in merged['annotation_notes']


def test_merge_ortholog_evidence_preserves_non_null_direct_values():
    direct = {'function': 'Direct function statement.'}
    ortholog = {'function': 'Ortholog function statement.'}
    hit = OrthologHit(
        source_organism_code='mory',
        source_organism_name=None,
        source_gene_id='MO_000001',
        source_gene_name=None,
        score=507.0,
        lookup_source='kegg_ssdb',
    )

    merged, filled = merge_ortholog_evidence(
        direct,
        ortholog,
        ['function'],
        hit,
    )

    assert filled == []
    assert merged['function'] == 'Direct function statement.'


def test_attach_ortholog_metadata_adds_top_hit_and_pass_block():
    hit = OrthologHit(
        source_organism_code='mory',
        source_organism_name='Mycobacterium orygis',
        source_gene_id='MO_000001',
        source_gene_name='dnaA',
        score=507.0,
        lookup_source='kegg_ssdb',
    )
    annotation = {
        'gene_id': 'Rv0001',
        'annotation_metadata': {},
    }
    pass_meta = build_ortholog_pass_metadata(
        ran=False,
        skipped_reason='no_eligible_missing_fields',
    )

    updated = attach_ortholog_metadata(annotation, hit, pass_meta)

    assert updated['annotation_metadata']['ortholog_top_hit']['source_gene_id'] == 'MO_000001'
    assert updated['annotation_metadata']['ortholog_pass']['skipped_reason'] == (
        'no_eligible_missing_fields'
    )


def test_merge_ortholog_annotation_treats_string_null_as_missing():
    hit = OrthologHit(
        source_organism_code="mmi",
        source_organism_name="Mycobacterium marinum",
        source_gene_id="MMAR_3491",
        source_gene_name=None,
        score=360.0,
        identity=0.736,
        lookup_source="kegg_ssdb",
    )
    direct = {
        "gene_id": "Rv1734c",
        "function": "null",
        "infection_impact": None,
        "annotation_metadata": {},
    }
    ortholog = {
        "function": "E2 component of pyruvate dehydrogenase.",
        "infection_impact": None,
    }
    merged, filled = metadata.merge_ortholog_annotation(
        direct,
        ortholog,
        ["function", "infection_impact"],
        hit,
        target_gene_id="Rv1734c",
    )

    assert merged["function"] == "E2 component of pyruvate dehydrogenase."
    assert merged["annotation_metadata"]["field_provenance"]["function"] == "ortholog_derived"
    assert "function" in filled


def test_null_out_other_locus_claims_clears_wrong_gene_text():
    annotation = {
        "gene_id": "Rv1734c",
        "function": None,
        "infection_impact": (
            "Rv0792c plays a key role in M. tuberculosis virulence "
            "(PMID: 36280199)"
        ),
        "annotation_metadata": {},
    }

    cleaned = metadata.null_out_other_locus_claims(annotation, expected_gene_id="Rv1734c")

    assert cleaned["infection_impact"] is None
    assert cleaned["gene_id"] == "Rv1734c"


def test_null_out_other_locus_claims_keeps_matching_locus_text():
    annotation = {
        "gene_id": "Rv1734c",
        "function": "Rv1734c encodes a conserved hypothetical protein.",
        "annotation_metadata": {},
    }

    cleaned = metadata.null_out_other_locus_claims(annotation, expected_gene_id="Rv1734c")

    assert cleaned["function"] == "Rv1734c encodes a conserved hypothetical protein."


def test_merge_fills_eligible_fields_after_wrong_locus_is_nulled():
    hit = OrthologHit(
        source_organism_code="mmi",
        source_organism_name="Mycobacterium marinum",
        source_gene_id="MMAR_3491",
        source_gene_name=None,
        score=360.0,
        identity=0.736,
        lookup_source="kegg_ssdb",
    )
    direct = metadata.null_out_other_locus_claims(
        {
            "gene_id": "Rv1734c",
            "function": None,
            "infection_impact": (
                "Rv0792c plays a key role in M. tuberculosis virulence."
            ),
            "annotation_metadata": {},
        },
        expected_gene_id="Rv1734c",
    )
    ortholog = {
        "function": "pyruvate dehydrogenase E2 ortholog function",
        "infection_impact": "MMAR_3491 infection phenotype in fish.",
    }
    merged, filled = metadata.merge_ortholog_annotation(
        direct,
        ortholog,
        ["function", "infection_impact"],
        hit,
        target_gene_id="Rv1734c",
    )

    assert merged["function"] == "pyruvate dehydrogenase E2 ortholog function"
    assert merged["infection_impact"] == "MMAR_3491 infection phenotype in fish."
    assert set(filled) == {"function", "infection_impact"}
    assert merged["annotation_metadata"]["field_provenance"]["function"] == "ortholog_derived"
    assert merged["annotation_metadata"]["field_provenance"]["infection_impact"] == (
        "ortholog_derived"
    )


def test_merge_ortholog_annotation_keeps_both_values():
    hit = OrthologHit(
        source_organism_code="mory",
        source_organism_name="Mycobacterium orygis",
        source_gene_id="MO_000001",
        source_gene_name="octT",
        score=2600.0,
        identity=0.62,
        lookup_source="kegg_ssdb",
    )
    direct = {
        "gene_id": "Rv0001",
        "name": "dnaA",
        "function": "target function text",
        "infection_impact": None,
        "annotation_metadata": {},
    }
    ortholog = {
        "function": "ortholog function text",
        "infection_impact": "ortholog infection text",
    }
    merged, filled = metadata.merge_ortholog_annotation(
        direct,
        ortholog,
        ["function", "infection_impact"],
        hit,
        target_gene_id="Rv0001",
        target_gene_name="dnaA",
    )

    # both present -> canonical value stays target, ortholog stored separately
    assert merged["function"] == "target function text"
    assert merged["annotation_metadata"]["field_provenance"]["function"] == "target_plus_ortholog"
    of = merged["annotation_metadata"]["ortholog_fields"]["function"]
    assert of["value"] == "ortholog function text"
    assert of["source_gene_id"] == "MO_000001"
    assert of["identity"] == 0.62

    # target empty -> canonical value becomes ortholog, provenance ortholog_derived
    assert merged["infection_impact"] == "ortholog infection text"
    assert merged["annotation_metadata"]["field_provenance"]["infection_impact"] == "ortholog_derived"

    assert set(filled) == {"function", "infection_impact"}
    assert merged["annotation_metadata"]["review_flags"]["function"] is True


def test_merge_ortholog_annotation_skips_empty_ortholog_values():
    from autoannotation import metadata, orthology

    hit = orthology.OrthologHit(
        source_organism_code="mory", source_organism_name="Mycobacterium orygis",
        source_gene_id="MO_1", source_gene_name=None,
        score=1.0, identity=0.5, lookup_source="kegg_ssdb",
    )
    direct = {"function": "target only", "infection_impact": None, "annotation_metadata": {}}
    ortholog = {"function": None, "infection_impact": None}
    merged, filled = metadata.merge_ortholog_annotation(
        direct, ortholog, ["function", "infection_impact"], hit,
        target_gene_id="Rv0001", target_gene_name="dnaA",
    )
    assert filled == []
    assert "ortholog_fields" not in merged["annotation_metadata"] or \
        merged["annotation_metadata"]["ortholog_fields"] == {}
    assert merged["function"] == "target only"


def test_merge_ortholog_annotation_does_not_mutate_input():
    from autoannotation import metadata, orthology

    hit = orthology.OrthologHit(
        source_organism_code="mory", source_organism_name="Mycobacterium orygis",
        source_gene_id="MO_000001", source_gene_name="octT",
        score=2600.0, identity=0.62, lookup_source="kegg_ssdb",
    )
    direct = {
        "gene_id": "Rv0001", "name": "dnaA",
        "function": None,
        "infection_impact": "target infection text",
        "annotation_notes": "original note.",
        "annotation_metadata": {
            "field_provenance": {"some_existing_key": "direct"},
            "review_flags": {"some_existing_key": True},
        },
    }
    ortholog = {
        "function": "ortholog function text",
        "infection_impact": "ortholog infection text",
    }
    before = copy.deepcopy(direct)

    merged, filled = metadata.merge_ortholog_annotation(
        direct, ortholog, ["function", "infection_impact"], hit,
        target_gene_id="Rv0001", target_gene_name="dnaA",
    )

    # the original input dict (and its nested sub-dicts) must be untouched
    assert direct == before
    assert direct["annotation_metadata"]["field_provenance"] == {"some_existing_key": "direct"}
    assert direct["annotation_metadata"]["review_flags"] == {"some_existing_key": True}
    assert direct["annotation_notes"] == "original note."
    # returned annotation must be a distinct object from the input
    assert merged is not direct
    assert merged["annotation_metadata"] is not direct["annotation_metadata"]


def test_merge_ortholog_annotation_preserves_preexisting_metadata():
    from autoannotation import metadata, orthology

    hit = orthology.OrthologHit(
        source_organism_code="mory", source_organism_name="Mycobacterium orygis",
        source_gene_id="MO_000001", source_gene_name="octT",
        score=2600.0, identity=0.62, lookup_source="kegg_ssdb",
    )
    direct = {
        "function": "target function text",
        "infection_impact": None,
        "annotation_metadata": {
            "field_provenance": {"some_existing_key": "direct"},
            "review_flags": {"some_existing_key": True},
            "ortholog_fields": {"other_field": {"value": "prior ortholog value"}},
        },
    }
    ortholog = {
        "function": "ortholog function text",
        "infection_impact": "ortholog infection text",
    }

    merged, filled = metadata.merge_ortholog_annotation(
        direct, ortholog, ["function", "infection_impact"], hit,
        target_gene_id="Rv0001", target_gene_name="dnaA",
    )

    meta = merged["annotation_metadata"]
    # pre-existing entries survive alongside the newly added ones
    assert meta["field_provenance"]["some_existing_key"] == "direct"
    assert meta["field_provenance"]["function"] == "target_plus_ortholog"
    assert meta["field_provenance"]["infection_impact"] == "ortholog_derived"
    assert meta["review_flags"]["some_existing_key"] is True
    assert meta["review_flags"]["function"] is True
    assert meta["review_flags"]["infection_impact"] is True
    assert meta["ortholog_fields"]["other_field"] == {"value": "prior ortholog value"}
    assert meta["ortholog_fields"]["function"]["value"] == "ortholog function text"
    assert set(filled) == {"function", "infection_impact"}


def test_merge_ortholog_annotation_appends_to_existing_notes():
    from autoannotation import metadata, orthology

    hit = orthology.OrthologHit(
        source_organism_code="mory", source_organism_name="Mycobacterium orygis",
        source_gene_id="MO_000001", source_gene_name="octT",
        score=2600.0, identity=0.62, lookup_source="kegg_ssdb",
    )
    direct = {
        "function": None,
        "annotation_notes": "original note.",
        "annotation_metadata": {},
    }
    ortholog = {"function": "ortholog function text"}

    merged, filled = metadata.merge_ortholog_annotation(
        direct, ortholog, ["function"], hit,
        target_gene_id="Rv0001", target_gene_name="dnaA",
    )

    assert filled == ["function"]
    notes = merged["annotation_notes"]
    assert notes.startswith("original note.")
    assert "MO_000001" in notes
    assert "curator review required" in notes


def test_merge_ortholog_annotation_sets_note_when_no_existing_notes():
    from autoannotation import metadata, orthology

    hit = orthology.OrthologHit(
        source_organism_code="mory", source_organism_name="Mycobacterium orygis",
        source_gene_id="MO_000001", source_gene_name="octT",
        score=2600.0, identity=0.62, lookup_source="kegg_ssdb",
    )
    direct = {"function": None, "annotation_metadata": {}}
    ortholog = {"function": "ortholog function text"}

    merged, filled = metadata.merge_ortholog_annotation(
        direct, ortholog, ["function"], hit,
        target_gene_id="Rv0001", target_gene_name="dnaA",
    )

    assert filled == ["function"]
    notes = merged["annotation_notes"]
    # no leading separator or "None" prefix when there were no prior notes
    assert not notes.startswith("\n")
    assert not notes.startswith("None")
    assert notes.startswith("Ortholog evidence added")
    assert "MO_000001" in notes
    assert "curator review required" in notes
