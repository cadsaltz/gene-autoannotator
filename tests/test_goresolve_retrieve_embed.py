from pathlib import Path

from goresolve.embeddings import FakeEmbedder
from goresolve.ontology import load_go_ontology
from goresolve.retrieve import build_shortlist, embedding_candidates

FIXTURE = Path('tests/fixtures/go/mini.obo')


def test_fake_embedder_ranks_cytokinesis_nearest():
    onto = load_go_ontology(FIXTURE)
    embedder = FakeEmbedder(dim=64)
    hits = embedding_candidates(
        onto, ['cytokinesis'], embedder, top_k=3, min_cosine=0.1,
    )
    assert hits[0].id == 'GO:0000910'
    assert hits[0].source == 'embedding'


def test_build_shortlist_dedupes_preferring_exact():
    onto = load_go_ontology(FIXTURE)
    embedder = FakeEmbedder(dim=64)
    shortlist = build_shortlist(
        onto,
        queries=('cytokinesis',),
        embedder=embedder,
        top_k=5,
        min_cosine=0.1,
    )
    ids = [c.id for c in shortlist]
    assert ids.count('GO:0000910') == 1
    assert next(c for c in shortlist if c.id == 'GO:0000910').source in {'exact', 'alias'}
