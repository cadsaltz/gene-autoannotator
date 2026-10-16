import json
from pathlib import Path

import pytest

from experiments.paper.scripts import sample_consensus_arms_sections as s

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = REPO_ROOT / "experiments/paper/fixtures/paper_snapshots/bias_cluster_v2.json"


@pytest.fixture(scope="module")
def items():
    return json.loads(FIXTURE.read_text())["items"]


def test_sampler_sizes(items):
    sampled = s.sample_sections(items, per_organism=40, seed=42)
    assert len(sampled) == 120
    for org in s.ORGANISMS:
        rows = [r for r in sampled if r["profile_id"] == org]
        assert len(rows) == 40
    assert len({r["trial_id"] for r in sampled}) == 120


def test_sampler_prefers_paper_diversity(items):
    sampled = s.sample_sections(items, per_organism=40, seed=42)
    for org in s.ORGANISMS:
        pool_papers = {r["pmc_id"] for r in items if r["profile_id"] == org}
        got = [r["pmc_id"] for r in sampled if r["profile_id"] == org]
        # every available paper is used once before any paper is used twice
        assert len(set(got)) == min(40, len(pool_papers))


def test_sampler_too_few_items_raises():
    rows = [{"profile_id": o, "pmc_id": "1", "trial_id": f"{o}-1"} for o in s.ORGANISMS]
    with pytest.raises(ValueError):
        s.sample_sections(rows, per_organism=2, seed=1)


def test_split_is_paper_disjoint_and_balanced(items):
    sampled = s.sample_sections(items, per_organism=40, seed=42)
    dev, test = s.split_papers(sampled, seed=42)
    assert dev and test
    assert not set(dev) & set(test)
    assert set(dev) | set(test) == {r["pmc_id"] for r in sampled}
    assert abs(len(dev) - len(test)) <= len(s.ORGANISMS)
    # each organism has papers on both sides
    for org in s.ORGANISMS:
        papers = {r["pmc_id"] for r in sampled if r["profile_id"] == org}
        assert papers & set(dev) and papers & set(test)


def test_seed_reproducibility(items):
    a = s.sample_sections(items, per_organism=40, seed=7)
    b = s.sample_sections(items, per_organism=40, seed=7)
    c = s.sample_sections(items, per_organism=40, seed=8)
    assert [r["trial_id"] for r in a] == [r["trial_id"] for r in b]
    assert {r["trial_id"] for r in a} != {r["trial_id"] for r in c}
    assert s.split_papers(a, seed=7) == s.split_papers(b, seed=7)


def test_double_label_ids(items):
    sampled = s.sample_sections(items, per_organism=40, seed=42)
    ids = s.pick_double_label_ids(sampled, fraction=0.15, seed=42)
    assert len(ids) == 18
    assert set(ids) <= {r["trial_id"] for r in sampled}
    assert ids == s.pick_double_label_ids(sampled, fraction=0.15, seed=42)


def test_stub_shape(items):
    stub = s.make_stub(items[0])
    assert set(stub) == {
        "trial_id", "gene_id", "gene_name", "profile_id", "pmc_id",
        "section", "excerpt_text", "fields", "needs_human",
    }
    assert stub["fields"] == {} and stub["needs_human"] is False


def test_cli_writes_outputs(tmp_path):
    rc = s.main(["--seed", "42", "--fixture", str(FIXTURE), "--out-dir", str(tmp_path)])
    assert rc == 0
    stubs = [json.loads(l) for l in (tmp_path / "stubs.jsonl").read_text().splitlines()]
    assert len(stubs) == 120
    manifest = json.loads((tmp_path / "sample_manifest.json").read_text())
    assert manifest["seed"] == 42 and manifest["total"] == 120
    assert manifest["per_organism"] == {o: 40 for o in s.ORGANISMS}
    assert manifest["trial_ids"] == [x["trial_id"] for x in stubs]
    dev = json.loads((tmp_path / "dev_papers.json").read_text())
    test = json.loads((tmp_path / "test_papers.json").read_text())
    assert not set(dev) & set(test)
    dbl = json.loads((tmp_path / "double_label_ids.json").read_text())
    assert len(dbl) == 18 and set(dbl) <= set(manifest["trial_ids"])
