import json
from pathlib import Path

import pytest

from autoannotation import orthology
from autoannotation.orthology import OrthologHit, lookup_top_ortholog, parse_ssdb_best_response


FIXTURE_DIR = Path(__file__).parent / 'fixtures' / 'kegg_ssdb'


def _load_fixture(name):
    return (FIXTURE_DIR / name).read_text(encoding='utf-8')


def test_parse_ssdb_best_skips_self_hit_and_returns_top_ortholog():
    html = _load_fixture('mtu_rv0001.html')

    hit = parse_ssdb_best_response(html, 'mtu')

    assert hit is not None
    assert hit.source_organism_code == 'mory'
    assert hit.source_gene_id == 'MO_000001'
    assert hit.score == 2615.0
    assert hit.lookup_source == 'kegg_ssdb'


def test_parse_ssdb_best_returns_none_when_only_self_hit():
    html = '<html><A HREF="/entry/mtu:Rv9999">mtu:Rv9999</A></html>'

    assert parse_ssdb_best_response(html, 'mtu') is None


def test_parse_ssdb_hits_returns_all_non_self_with_identity():
    from autoannotation import orthology

    html = (
        '<A HREF="/entry/mtu:Rv0001">mtu:Rv0001</A> (507 a.a.) '
        '<A HREF="/entry/K02313">K02313</a>     507     2615     1.000      507\n'
        '<A HREF="/entry/mory:MO_000001">mory:MO_000001</A> initiator '
        '<A HREF="/entry/K02313">K02313</a>     507     2615     0.980      507\n'
        '<A HREF="/entry/msm:MSMEG_6947">msm:MSMEG_6947</A> initiator '
        '<A HREF="/entry/K02313">K02313</a>     504     2400     0.805      508\n'
    )
    hits = orthology.parse_ssdb_hits(html, "mtu")

    assert [h.source_organism_code for h in hits] == ["mory", "msm"]
    assert hits[0].source_gene_id == "MO_000001"
    assert hits[0].identity == 0.980
    assert hits[1].identity == 0.805
    # score is the SW-similarity column, not gene length
    assert hits[0].score == 2615.0
    assert hits[1].score == 2400.0


def test_lookup_top_ortholog_uses_cache(tmp_path):
    html = _load_fixture('mtu_rv0001.html')
    calls = {'count': 0}

    def fetch_html(_url):
        calls['count'] += 1
        return html

    hit1 = lookup_top_ortholog('mtu', 'Rv0001', cache_dir=tmp_path, fetch_html=fetch_html)
    hit2 = lookup_top_ortholog('mtu', 'Rv0001', cache_dir=tmp_path, fetch_html=fetch_html)

    assert hit1 == hit2
    assert calls['count'] == 1


def test_lookup_best_profiled_ortholog_uses_selection(tmp_path):
    from autoannotation import orthology

    html = (
        '<A HREF="/entry/mtu:Rv0001">mtu:Rv0001</A> (507 a.a.) '
        '<A HREF="/entry/K02313">K02313</a>     507     2615     1.000      507\n'
        '<A HREF="/entry/pspi:PSP_1">pspi:PSP_1</A> initiator '
        '<A HREF="/entry/K02313">K02313</a>     600     3000     0.900      600\n'
        '<A HREF="/entry/mory:MO_000001">mory:MO_000001</A> initiator '
        '<A HREF="/entry/K02313">K02313</a>     507     2600     0.620      507\n'
    )
    hit = orthology.lookup_best_profiled_ortholog(
        "mtu", "Rv0001", cache_dir=str(tmp_path), fetch_html=lambda url: html,
    )
    assert hit.source_organism_code == "mory"


def test_build_manual_ortholog_hit_uses_profile_code():
    from autoannotation import orthology, organisms

    profile = organisms.resolve_profile("mtb-h37rv")
    hit = orthology.build_manual_ortholog_hit(profile, "Rv9999", name="testA")
    assert hit.lookup_source == "manual"
    assert hit.source_gene_id == "Rv9999"
    assert hit.source_gene_name == "testA"
    assert hit.source_organism_code == "mtu"
    assert hit.identity is None


def test_lookup_top_ortholog_returns_none_without_kegg_code(tmp_path):
    assert lookup_top_ortholog(None, 'Rv0001', cache_dir=tmp_path) is None
    assert lookup_top_ortholog('mtu', None, cache_dir=tmp_path) is None


def test_lookup_top_ortholog_handles_fetch_failure(tmp_path):
    def fetch_html(_url):
        raise ConnectionError('network down')

    assert lookup_top_ortholog('mtu', 'Rv0001', cache_dir=tmp_path, fetch_html=fetch_html) is None


def test_ortholog_hit_to_metadata():
    hit = OrthologHit(
        source_organism_code='msm',
        source_organism_name='Mycobacterium smegmatis',
        source_gene_id='MSMEG_0001',
        source_gene_name='dnaA',
        score=500.0,
        lookup_source='kegg_ssdb',
    )

    payload = hit.to_metadata()

    assert payload['source_organism_code'] == 'msm'
    assert payload['source_gene_id'] == 'MSMEG_0001'
    assert payload['score'] == 500.0


def test_profile_for_kegg_organism_uses_builtin_profile():
    profile = orthology.profile_for_kegg_organism('mtu')

    assert profile.profile_id == 'mtb-h37rv'
    assert profile.kegg_organism_code == 'mtu'


def test_profile_for_kegg_organism_uses_msm_catalog_profile():
    profile = orthology.profile_for_kegg_organism('msm')

    assert profile.profile_id == 'msm-mc2155'
    assert profile.kegg_organism_code == 'msm'


def test_profile_for_kegg_organism_resolves_profile_id_fallback():
    profile = orthology.profile_for_kegg_organism('tcruzi-clbrener')
    assert 'Trypanosoma cruzi' in profile.species_name

    mory = orthology.profile_for_kegg_organism('mory')
    assert 'Mycobacterium orygis' in mory.species_name


def test_supports_ortholog_literature_pass():
    mory = OrthologHit(
        source_organism_code='mory',
        source_organism_name='Mycobacterium orygis',
        source_gene_id='MO_000001',
        source_gene_name='dnaA',
        score=500.0,
        lookup_source='kegg_ssdb',
    )
    pspi = OrthologHit(
        source_organism_code='pspi',
        source_organism_name=None,
        source_gene_id='PS2015_1409',
        source_gene_name='Ferredoxin, 4Fe-4S',
        score=108.0,
        lookup_source='kegg_ssdb',
    )

    assert orthology.supports_ortholog_literature_pass(mory) is True
    assert orthology.supports_ortholog_literature_pass(pspi) is False
    assert orthology.supports_ortholog_literature_pass(None) is False


def test_select_best_profiled_ortholog_prefers_profiled_over_top_score():
    from autoannotation import orthology

    unprofiled_top = orthology.OrthologHit(
        source_organism_code="pspi", source_organism_name=None,
        source_gene_id="PSPPH_1", source_gene_name=None,
        score=3000.0, identity=0.90, lookup_source="kegg_ssdb",
    )
    profiled = orthology.OrthologHit(
        source_organism_code="mory", source_organism_name="Mycobacterium orygis",
        source_gene_id="MO_000001", source_gene_name="dnaA",
        score=2600.0, identity=0.62, lookup_source="kegg_ssdb",
    )
    chosen = orthology.select_best_profiled_ortholog([unprofiled_top, profiled])
    assert chosen.source_organism_code == "mory"


def test_select_best_profiled_ortholog_can_restrict_to_organism():
    from autoannotation import orthology

    mory = orthology.OrthologHit(
        source_organism_code="mory", source_organism_name="Mycobacterium orygis",
        source_gene_id="MO_000001", source_gene_name="dnaA",
        score=2600.0, identity=0.62, lookup_source="kegg_ssdb",
    )
    msm = orthology.OrthologHit(
        source_organism_code="msm", source_organism_name=None,
        source_gene_id="MSMEG_1", source_gene_name=None,
        score=2800.0, identity=0.70, lookup_source="kegg_ssdb",
    )
    chosen = orthology.select_best_profiled_ortholog(
        [mory, msm], restrict_to_organism_code="mory",
    )
    assert chosen.source_organism_code == "mory"
    assert chosen.source_gene_id == "MO_000001"


def test_lookup_best_profiled_ortholog_restricts_to_organism(tmp_path):
    from autoannotation import orthology

    html = (
        '<A HREF="/entry/mtu:Rv0001">mtu:Rv0001</A> (507 a.a.) '
        '<A HREF="/entry/K02313">K02313</a>     507     2615     1.000      507\n'
        '<A HREF="/entry/msm:MSMEG_6947">msm:MSMEG_6947</A> initiator '
        '<A HREF="/entry/K02313">K02313</a>     504     2800     0.805      508\n'
        '<A HREF="/entry/mory:MO_000001">mory:MO_000001</A> initiator '
        '<A HREF="/entry/K02313">K02313</a>     507     2600     0.620      507\n'
    )
    hit = orthology.lookup_best_profiled_ortholog(
        "mtu",
        "Rv0001",
        cache_dir=str(tmp_path),
        fetch_html=lambda url: html,
        restrict_to_organism_code="mory",
    )
    assert hit.source_organism_code == "mory"
    assert hit.source_gene_id == "MO_000001"


def test_select_best_profiled_ortholog_rejects_below_identity_floor():
    from autoannotation import orthology

    weak = orthology.OrthologHit(
        source_organism_code="mory", source_organism_name="Mycobacterium orygis",
        source_gene_id="MO_000001", source_gene_name="dnaA",
        score=2600.0, identity=0.10, lookup_source="kegg_ssdb",
    )
    assert orthology.select_best_profiled_ortholog([weak]) is None


def test_select_best_profiled_ortholog_ranks_profiled_by_score():
    from autoannotation import orthology

    lower = orthology.OrthologHit(
        source_organism_code="mory", source_organism_name=None,
        source_gene_id="MO_1", source_gene_name=None,
        score=2000.0, identity=0.60, lookup_source="kegg_ssdb",
    )
    higher = orthology.OrthologHit(
        source_organism_code="msm", source_organism_name=None,
        source_gene_id="MSMEG_1", source_gene_name=None,
        score=2500.0, identity=0.55, lookup_source="kegg_ssdb",
    )
    chosen = orthology.select_best_profiled_ortholog([lower, higher])
    assert chosen.source_organism_code == "msm"


def test_resolve_ortholog_gene_name_does_not_borrow_target_symbol(tmp_path):
    """Descriptive KEGG product names should fall back to the ortholog locus,
    never the target gene symbol (that would search the wrong organism papers)."""
    hit = OrthologHit(
        source_organism_code='mory',
        source_organism_name='Mycobacterium orygis',
        source_gene_id='MO_002536',
        source_gene_name='diglucosylglycerate octanoyltransferase',
        score=247.0,
        lookup_source='kegg_ssdb',
    )

    assert orthology.resolve_ortholog_gene_name(
        hit,
        tmp_path,
        target_gene_name='octT',
    ) == 'MO_002536'


def test_resolve_ortholog_gene_name_falls_back_to_locus_without_symbol(tmp_path):
    hit = OrthologHit(
        source_organism_code='mory',
        source_organism_name='Mycobacterium orygis',
        source_gene_id='MO_002536',
        source_gene_name='diglucosylglycerate octanoyltransferase',
        score=247.0,
        lookup_source='kegg_ssdb',
    )

    assert orthology.resolve_ortholog_gene_name(hit, tmp_path) == 'MO_002536'


def test_resolve_ortholog_gene_name_keeps_short_kegg_name(tmp_path):
    hit = OrthologHit(
        source_organism_code='mory',
        source_organism_name='Mycobacterium orygis',
        source_gene_id='MO_000001',
        source_gene_name='dnaA',
        score=507.0,
        lookup_source='kegg_ssdb',
    )

    assert orthology.resolve_ortholog_gene_name(hit, tmp_path) == 'dnaA'


def test_fetch_ssdb_hits_reads_legacy_single_dict_cache(tmp_path):
    legacy = OrthologHit(
        source_organism_code='mory',
        source_organism_name='Mycobacterium orygis',
        source_gene_id='MO_000001',
        source_gene_name='dnaA',
        score=2615.0,
        identity=0.98,
        lookup_source='kegg_ssdb',
    ).to_metadata()
    cache_file = Path(orthology._cache_path(str(tmp_path), 'mtu', 'Rv0001'))
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(legacy), encoding='utf-8')

    def fetch_html(_url):
        raise AssertionError('should not refetch when a cache file exists')

    hits = orthology._fetch_ssdb_hits('mtu', 'Rv0001', cache_dir=str(tmp_path), fetch_html=fetch_html)

    assert len(hits) == 1
    assert isinstance(hits[0], OrthologHit)
    assert hits[0].source_gene_id == 'MO_000001'
    assert hits[0].identity == 0.98

    top = lookup_top_ortholog('mtu', 'Rv0001', cache_dir=str(tmp_path), fetch_html=fetch_html)
    assert top.source_gene_id == 'MO_000001'


def test_fetch_ssdb_hits_reads_null_cache_without_fetch(tmp_path):
    cache_file = Path(orthology._cache_path(str(tmp_path), 'mtu', 'Rv0001'))
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text('null', encoding='utf-8')

    def fetch_html(_url):
        raise AssertionError('should not refetch when cache is null')

    assert orthology._fetch_ssdb_hits(
        'mtu', 'Rv0001', cache_dir=str(tmp_path), fetch_html=fetch_html
    ) == []
    assert lookup_top_ortholog(
        'mtu', 'Rv0001', cache_dir=str(tmp_path), fetch_html=fetch_html
    ) is None


def test_fetch_ssdb_hits_refetches_on_corrupt_cache(tmp_path):
    cache_file = Path(orthology._cache_path(str(tmp_path), 'mtu', 'Rv0001'))
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text('{not valid json', encoding='utf-8')

    html = _load_fixture('mtu_rv0001.html')
    calls = {'count': 0}

    def fetch_html(_url):
        calls['count'] += 1
        return html

    hits = orthology._fetch_ssdb_hits('mtu', 'Rv0001', cache_dir=str(tmp_path), fetch_html=fetch_html)

    assert calls['count'] == 1
    assert hits
    assert hits[0].source_organism_code == 'mory'


def test_build_manual_ortholog_hit_falls_back_to_profile_id():
    from autoannotation import organisms

    profile = organisms.OrganismProfile(
        profile_id='CustomOrg',
        canonical_name='Custom organism',
        species_name='Custom organism',
        strain=None,
        synonyms=(),
        species_synonyms=(),
        strain_synonyms=(),
        locus_regex=r'^.+$',
        search_terms=(),
        kegg_organism_code=None,
    )
    hit = orthology.build_manual_ortholog_hit(profile, 'LOCUS1', name='geneX')

    assert hit.source_organism_code == 'customorg'
    assert hit.source_gene_id == 'LOCUS1'
    assert hit.source_gene_name == 'geneX'
    assert hit.lookup_source == 'manual'
    assert hit.identity is None
