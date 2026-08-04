"""Pure comparison metrics (no ML model imports)."""

COVERAGE_SCORE_WEIGHT = 0.75
SYMMETRIC_SCORE_WEIGHT = 0.25

VERBOSITY_LENGTH_RATIO_THRESHOLD = 4.0
VERBOSITY_MAX_PENALTY = 0.12


def is_unknown(v):
	if v is None:
		return True
	if isinstance(v, list):
		return len(v) == 0
	return v == '' or v == 'unknown' or v == 'missing'


def stringify_field_value(value):
	if isinstance(value, list):
		return ', '.join(str(item) for item in value if item is not None)
	if isinstance(value, bool):
		return str(value).lower()
	return str(value)


def verbosity_length_ratio(trusted_val, generated_val):
	trusted_len = len(stringify_field_value(trusted_val).strip())
	generated_len = len(stringify_field_value(generated_val).strip())
	if trusted_len == 0:
		return 1.0
	return generated_len / trusted_len


def apply_verbosity_dampening(score, length_ratio):
	if length_ratio <= VERBOSITY_LENGTH_RATIO_THRESHOLD:
		return score
	penalty = min(
		VERBOSITY_MAX_PENALTY,
		(length_ratio - VERBOSITY_LENGTH_RATIO_THRESHOLD) * 0.02,
	)
	return max(0.0, score - penalty)


def combine_similarity_scores(coverage_score, symmetric_score, length_ratio):
	blended = (
		COVERAGE_SCORE_WEIGHT * coverage_score
		+ SYMMETRIC_SCORE_WEIGHT * symmetric_score
	)
	return apply_verbosity_dampening(min(1.0, blended), length_ratio)
