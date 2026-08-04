from compareannotations.metrics import (
	apply_verbosity_dampening,
	combine_similarity_scores,
	is_unknown,
	verbosity_length_ratio,
)


def test_is_unknown_treats_null_as_unknown():
	assert is_unknown(None)
	assert not is_unknown('DNA replication initiator')


def test_verbosity_length_ratio():
	assert verbosity_length_ratio('short', 'a much longer generated field') > 4.0


def test_combine_similarity_scores_prefers_coverage():
	# Strong coverage, weak symmetric (typical when generated is a superset).
	blended = combine_similarity_scores(
		coverage_score=0.92,
		symmetric_score=0.45,
		length_ratio=2.0,
	)
	assert blended > 0.75
	assert blended < 0.95


def test_verbosity_dampening_is_mild_for_long_generated():
	high_coverage = combine_similarity_scores(0.9, 0.4, length_ratio=8.0)
	no_dampen = combine_similarity_scores(0.9, 0.4, length_ratio=2.0)
	assert high_coverage >= no_dampen - 0.15
	assert high_coverage > 0.65


def test_apply_verbosity_dampening_no_penalty_under_threshold():
	assert apply_verbosity_dampening(0.9, 3.0) == 0.9
