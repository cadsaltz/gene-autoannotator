import errno
import json
from unittest.mock import mock_open, patch

import pandas as pd

from autoannotation import gene_names
from autoannotation import organisms


def test_gene_name_record_round_trips_to_cache_dict():
    record = gene_names.GeneNameRecord(
        profile_id="tcruzi-clbrener",
        locus="TcCLB.507093.220",
        gene_name="TcUBP1",
        source="manual_cache",
        source_detail="Curated from PMID 37160607",
        confidence="curated",
        aliases=["UBP1"],
        looked_up_at="2026-05-20T00:00:00+00:00",
    )

    restored = gene_names.GeneNameRecord.from_dict(record.to_dict())

    assert restored == record


def test_cache_lookup_returns_manual_cache_source(tmp_path):
    cache_dir = tmp_path / "gene_names"
    cache_dir.mkdir()
    cache_file = cache_dir / "tcruzi-clbrener.json"
    cache_file.write_text(json.dumps({
        "TcCLB.507093.220": {
            "profile_id": "tcruzi-clbrener",
            "locus": "TcCLB.507093.220",
            "gene_name": "TcUBP1",
            "source": "manual_cache",
            "source_detail": "Curated from literature",
            "confidence": "curated",
            "aliases": ["UBP1"],
            "looked_up_at": "2026-05-20T00:00:00+00:00",
        }
    }))

    result = gene_names.lookup_cached_gene_name(
        organisms.resolve_profile("tcruzi-clbrener"),
        "TcCLB.507093.220",
        cache_dir,
    )

    assert result.gene_name == "TcUBP1"
    assert result.source == "manual_cache"
    assert result.aliases == ["UBP1"]


def test_cache_lookup_returns_cache_source_for_online_records(tmp_path):
    cache_dir = tmp_path / "gene_names"
    cache_dir.mkdir()
    cache_file = cache_dir / "tcruzi-clbrener.json"
    cache_file.write_text(json.dumps({
        "TcCLB.507093.220": {
            "profile_id": "tcruzi-clbrener",
            "locus": "TcCLB.507093.220",
            "gene_name": "TcUBP1",
            "source": "ncbi_gene",
            "source_detail": "NCBI Gene esummary",
            "confidence": "clear",
            "aliases": [],
            "looked_up_at": "2026-05-20T00:00:00+00:00",
        }
    }))

    result = gene_names.lookup_cached_gene_name(
        organisms.resolve_profile("tcruzi-clbrener"),
        "TcCLB.507093.220",
        cache_dir,
    )

    assert result.source == "cache"
    assert result.source_detail == "Cached ncbi_gene: NCBI Gene esummary"


def test_cache_lookup_ignores_corrupt_cache(tmp_path):
    cache_dir = tmp_path / "gene_names"
    cache_dir.mkdir()
    (cache_dir / "tcruzi-clbrener.json").write_text("{not json")

    result = gene_names.lookup_cached_gene_name(
        organisms.resolve_profile("tcruzi-clbrener"),
        "TcCLB.507093.220",
        cache_dir,
    )

    assert result is None


def test_write_cached_gene_name_persists_by_profile_and_locus(tmp_path):
    record = gene_names.GeneNameRecord(
        profile_id="tcruzi-clbrener",
        locus="TcCLB.507093.220",
        gene_name="TcUBP1",
        source="ncbi_gene",
        source_detail="NCBI Gene esummary",
        confidence="clear",
        aliases=[],
        looked_up_at="2026-05-20T00:00:00+00:00",
    )

    gene_names.write_cached_gene_name(record, tmp_path)

    payload = json.loads((tmp_path / "tcruzi-clbrener.json").read_text())
    assert payload["TcCLB.507093.220"]["gene_name"] == "TcUBP1"


def test_write_cached_gene_name_swallows_enospc(tmp_path, caplog):
    record = gene_names.GeneNameRecord(
        profile_id="tcruzi-clbrener",
        locus="TcCLB.507093.220",
        gene_name="TcUBP1",
        source="ncbi_gene",
        source_detail="NCBI Gene esummary",
        confidence="clear",
        aliases=[],
        looked_up_at="2026-05-20T00:00:00+00:00",
    )

    enospc = OSError(errno.ENOSPC, "No space left on device")
    with patch("builtins.open", mock_open()) as mocked_open:
        mocked_open.side_effect = enospc
        gene_names.write_cached_gene_name(record, tmp_path)

    assert any("No space left on device" in r.message or "ENOSPC" in r.message or
               "disk" in r.message.lower() for r in caplog.records)


def test_annotation_table_lookup_returns_gene_name(monkeypatch):
    profile = organisms.resolve_profile("mtb-h37rv")
    table = pd.DataFrame([
        {"Feature": "CDS", "Locus": "Rv0001", "Name": "dnaA"}
    ])
    monkeypatch.setattr(gene_names.pd, "read_csv", lambda *args, **kwargs: table)

    result = gene_names.lookup_annotation_table_gene_name(profile, "Rv0001")

    assert result.gene_name == "dnaA"
    assert result.source == "annotation_table"


def test_annotation_table_lookup_locus_from_exact_gene_name(monkeypatch):
    profile = organisms.resolve_profile("mtb-h37rv")
    table = pd.DataFrame([
        {"Feature": "CDS", "Locus": "Rv0001", "Name": "dnaA"},
        {"Feature": "CDS", "Locus": "Rv0002", "Name": "dnaN"},
    ])
    monkeypatch.setattr(gene_names.pd, "read_csv", lambda *args, **kwargs: table)

    result = gene_names.lookup_locus_from_annotation_table(profile, "dnaA")

    assert result is not None
    assert result.locus == "Rv0001"
    assert result.source == "annotation_table"
    assert result.confidence == "profile_table"


def test_annotation_table_lookup_locus_case_insensitive_unique(monkeypatch):
    profile = organisms.resolve_profile("mtb-h37rv")
    table = pd.DataFrame([
        {"Feature": "CDS", "Locus": "Rv0001", "Name": "dnaA"},
    ])
    monkeypatch.setattr(gene_names.pd, "read_csv", lambda *args, **kwargs: table)

    result = gene_names.lookup_locus_from_annotation_table(profile, "DNAA")

    assert result.locus == "Rv0001"


def test_annotation_table_lookup_locus_ambiguous(monkeypatch):
    profile = organisms.resolve_profile("mtb-h37rv")
    table = pd.DataFrame([
        {"Feature": "CDS", "Locus": "Rv0001", "Name": "dup"},
        {"Feature": "CDS", "Locus": "Rv0002", "Name": "dup"},
    ])
    monkeypatch.setattr(gene_names.pd, "read_csv", lambda *args, **kwargs: table)

    result = gene_names.lookup_locus_from_annotation_table(profile, "dup")

    assert result.locus is None
    assert set(result.candidates) == {"Rv0001", "Rv0002"}
    assert "ambiguous_locus" in result.warnings


def test_annotation_table_lookup_locus_by_locus_column_case_insensitive(monkeypatch):
    profile = organisms.resolve_profile("mtb-h37rv")
    table = pd.DataFrame([
        {"Feature": "CDS", "Locus": "Rv0001", "Name": "dnaA"},
    ])
    monkeypatch.setattr(gene_names.pd, "read_csv", lambda *args, **kwargs: table)

    result = gene_names.lookup_locus_from_annotation_table(profile, "rv0001")

    assert result.locus == "Rv0001"


class FakeSource:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def lookup(self, profile, locus):
        self.calls.append((profile.profile_id, locus))
        return self.result


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(self.payloads.pop(0))


def test_ncbi_gene_source_returns_clear_gene_name():
    session = FakeSession([
        {"esearchresult": {"idlist": ["123"]}},
        {"result": {"123": {"name": "dnaA", "otheraliases": "dnaN, dnaX"}}},
    ])
    source = gene_names.NcbiGeneSource(session=session)

    result = source.lookup(organisms.resolve_profile("mtb-h37rv"), "Rv0001")

    assert result.gene_name == "dnaA"
    assert result.source == "ncbi_gene"
    assert result.aliases == ["dnaN", "dnaX"]
    assert "db=gene" in session.calls[0][0]


def test_ncbi_gene_source_marks_multiple_hits_ambiguous():
    source = gene_names.NcbiGeneSource(session=FakeSession([
        {"esearchresult": {"idlist": ["123", "456"]}},
    ]))

    result = source.lookup(organisms.resolve_profile("mtb-h37rv"), "Rv0001")

    assert result.gene_name is None
    assert result.candidates == ["123", "456"]
    assert "ambiguous_gene_name" in result.warnings


def test_uniprot_source_returns_single_gene_candidate():
    source = gene_names.UniProtSource(session=FakeSession([
        {
            "results": [
                {"genes": [{"geneName": {"value": "TcUBP1"}}]},
                {"genes": [{"geneName": {"value": "TcUBP1"}}]},
            ]
        }
    ]))

    result = source.lookup(
        organisms.resolve_profile("tcruzi-clbrener"),
        "TcCLB.507093.220",
    )

    assert result.gene_name == "TcUBP1"
    assert result.source == "uniprot"


def test_resolver_order_uses_cache_before_online_source(tmp_path):
    profile = organisms.resolve_profile("tcruzi-clbrener")
    gene_names.write_cached_gene_name(
        gene_names.GeneNameRecord(
            profile_id=profile.profile_id,
            locus="TcCLB.507093.220",
            gene_name="TcUBP1",
            source="manual_cache",
            source_detail="Curated",
            confidence="curated",
            aliases=[],
            looked_up_at="2026-05-20T00:00:00+00:00",
        ),
        tmp_path,
    )
    online_source = FakeSource(gene_names.GeneNameLookupResult(
        gene_name="WrongName",
        source="ncbi_gene",
        source_detail="fake",
    ))

    result = gene_names.resolve_gene_name(
        profile,
        "TcCLB.507093.220",
        cache_dir=tmp_path,
        sources=[online_source],
    )

    assert result.gene_name == "TcUBP1"
    assert result.source == "manual_cache"
    assert online_source.calls == []


def test_resolver_online_hit_writes_cache(tmp_path):
    profile = organisms.resolve_profile("tcruzi-clbrener")
    online_source = FakeSource(gene_names.GeneNameLookupResult(
        gene_name="TcUBP1",
        source="ncbi_gene",
        source_detail="fake",
        confidence="clear",
    ))

    result = gene_names.resolve_gene_name(
        profile,
        "TcCLB.507093.220",
        cache_dir=tmp_path,
        sources=[online_source],
    )

    assert result.gene_name == "TcUBP1"
    assert json.loads((tmp_path / "tcruzi-clbrener.json").read_text())[
        "TcCLB.507093.220"
    ]["gene_name"] == "TcUBP1"


def test_resolver_ambiguous_online_result_falls_back_to_locus(tmp_path):
    profile = organisms.resolve_profile("tcruzi-clbrener")
    online_source = FakeSource(gene_names.GeneNameLookupResult(
        gene_name=None,
        source="ncbi_gene",
        source_detail="fake",
        candidates=["TcUBP1", "TcUBP2"],
        warnings=["ambiguous_gene_name"],
    ))

    result = gene_names.resolve_gene_name(
        profile,
        "TcCLB.507093.220",
        cache_dir=tmp_path,
        sources=[online_source],
    )

    assert result.gene_name == "TcCLB.507093.220"
    assert result.source == "locus_fallback"
    assert result.candidates == ["TcUBP1", "TcUBP2"]


def test_locus_resolver_skips_sources_without_lookup_locus_and_preserves_no_hit_details():
    class GeneNameOnlySource:
        def lookup(self, profile, locus):
            raise AssertionError("locus resolver should not call gene-name lookup")

    class NoLocusSource:
        def lookup_locus(self, profile, gene_name):
            return gene_names.GeneLocusLookupResult(
                locus=None,
                source="test_no_locus",
                source_detail="ambiguous test fixture",
                candidates=["CUS_0001", "CUS_0002"],
                warnings=["ambiguous_locus"],
            )

    result = gene_names.resolve_locus_from_gene_name(
        organisms.resolve_profile("mtb-h37rv"),
        "abc1",
        allow_online_lookup=True,
        sources=[GeneNameOnlySource(), NoLocusSource()],
    )

    assert result.locus is None
    assert result.source == "test_no_locus"
    assert result.source_detail == "ambiguous test fixture"
    assert result.candidates == ["CUS_0001", "CUS_0002"]
    assert result.warnings == ["ambiguous_locus"]
