import json
from unittest.mock import patch

import pandas as pd

from autoannotation import ortholog_lookup
from autoannotation.orthology import OrthologHit


def test_ortholog_lookup_cli_prints_hit(monkeypatch, capsys, tmp_path):
    mycobrowser_df = pd.DataFrame([
        {'Feature': 'CDS', 'Locus': 'Rv0001', 'Name': 'dnaA'},
    ])
    monkeypatch.setattr(
        ortholog_lookup.targets.organisms.gene_names.pd,
        'read_csv',
        lambda *args, **kwargs: mycobrowser_df,
    )
    fake_hit = OrthologHit(
        source_organism_code='mory',
        source_organism_name='Mycobacterium orygis',
        source_gene_id='MO_000001',
        source_gene_name='dnaA',
        score=507.0,
        lookup_source='kegg_ssdb',
    )
    with patch.object(ortholog_lookup.orthology, 'lookup_top_ortholog', return_value=fake_hit):
        exit_code = ortholog_lookup.main(['mtb-h37rv', 'Rv0001', '--cache-dir', str(tmp_path)])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload['kegg_organism_code'] == 'mtu'
    assert payload['kegg_query'] == 'mtu:Rv0001'
    assert payload['ortholog_top_hit']['source_gene_id'] == 'MO_000001'


def test_ortholog_lookup_cli_returns_nonzero_without_hit(monkeypatch, capsys, tmp_path):
    mycobrowser_df = pd.DataFrame([
        {'Feature': 'CDS', 'Locus': 'Rv0001', 'Name': 'dnaA'},
    ])
    monkeypatch.setattr(
        ortholog_lookup.targets.organisms.gene_names.pd,
        'read_csv',
        lambda *args, **kwargs: mycobrowser_df,
    )
    with patch.object(ortholog_lookup.orthology, 'lookup_top_ortholog', return_value=None):
        exit_code = ortholog_lookup.main(['--profile', 'mtb-h37rv', '--locus', 'Rv0001'])

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload['ortholog_top_hit'] is None
    assert any(w['code'] == 'no_ortholog_hit' for w in payload['warnings'])


def test_ortholog_lookup_applies_kegg_locus_regex(monkeypatch, tmp_path):
    from autoannotation import organisms

    profile = organisms.OrganismProfile(
        profile_id='tcruzi-clbrener',
        canonical_name='Trypanosoma cruzi CL Brener',
        species_name='Trypanosoma cruzi',
        strain='CL Brener',
        synonyms=(),
        species_synonyms=(),
        strain_synonyms=(),
        locus_regex=r'^TcCLB\.\d+\.\d+$',
        search_terms=('Trypanosoma cruzi',),
        kegg_organism_code='tcr',
        kegg_locus_regex=r'^TcCLB\.(.+)$',
    )
    fake_target = type(
        'T',
        (),
        {
            'profile': profile,
            'resolved_locus': 'TcCLB.507297.10',
            'submitted_locus': 'TcCLB.507297.10',
            'resolved_name': None,
            'primary_identifier': 'TcCLB.507297.10',
            'warnings': (),
        },
    )()
    captured = {}

    def fake_lookup(kegg_code, gene_locus, **kwargs):
        captured['query'] = f'{kegg_code}:{gene_locus}'
        return OrthologHit(
            source_organism_code='tbr',
            source_organism_name='Trypanosoma brucei',
            source_gene_id='Tb927.6.1030',
            source_gene_name='cysteine peptidase precursor',
            score=875.0,
            identity=0.658,
            lookup_source='kegg_ssdb',
        )

    monkeypatch.setattr(
        ortholog_lookup.targets,
        'resolve_annotation_target',
        lambda **kwargs: fake_target,
    )
    monkeypatch.setattr(ortholog_lookup.orthology, 'lookup_top_ortholog', fake_lookup)

    payload = ortholog_lookup.lookup_for_target(
        profile='tcruzi-clbrener',
        locus='TcCLB.507297.10',
        cache_dir=str(tmp_path),
    )

    assert payload['resolved_locus'] == 'TcCLB.507297.10'
    assert payload['kegg_locus'] == '507297.10'
    assert payload['kegg_query'] == 'tcr:507297.10'
    assert captured['query'] == 'tcr:507297.10'
    assert payload['ortholog_top_hit']['source_gene_id'] == 'Tb927.6.1030'
