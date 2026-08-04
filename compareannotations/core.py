
import json
import logging
import time

from autoannotation.metadata import COMPARISON_IGNORE_FIELDS

from .functional_category import functional_category_similarity
from .metrics import (
	combine_similarity_scores,
	is_unknown,
	stringify_field_value,
	verbosity_length_ratio,
)
from .scoring import (
	embedded_similarity,
	field_values_equal,
	llm_coverage_similarity,
	llm_similarity,
	trusted_coverage_similarity,
)

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)

FIELD_WEIGHTS = {
	"rv_id": 0.0,
	"name": 0.0,
	"function": 3.0,
	"infection_impact": 1.5
}

def load_json(path):

	with open(path, "r") as f:
		return json.load(f)

def compare(trusted, generated):
	start = time.time()
	log.info('Starting annotation comparison (%d trusted keys, %d generated keys)',
		len(trusted), len(generated))

	field_scores = {}
	ignored = []
	scored_count = 0

	for key in trusted:
		if key in COMPARISON_IGNORE_FIELDS:
			log.debug('Skipping metadata field: %s', key)
			ignored.append(key)
			continue

		trusted_val = trusted.get(key)

		if is_unknown(trusted_val):
			log.debug('Skipping field with unknown trusted value: %s', key)
			ignored.append(key)
			continue

		scored_count += 1
		log.info('Scoring field %d: %s', scored_count, key)
		field_scores[key] = score_field(key, trusted, generated)

	missing = [key for key in trusted.keys() if key not in generated and key not in ignored]
	extra = list(set(generated.keys()) - set(trusted.keys()))

	if missing:
		log.warning('Generated missing trusted fields: %s', ', '.join(missing))
	if extra:
		log.debug('Extra generated fields (not scored): %s', ', '.join(extra))

	avg_embed, avg_llm, avg_coverage = compute_average_scores(field_scores)

	report = {
		"trusted": trusted,
		"generated": generated,
		"ignored": ignored,
		"field_scores": field_scores,
		"missing": missing,
		"extra": extra,
		"exact_matches": [key for key, value in field_scores.items() if value["exact"] == 1 ],
		"avg_embed": avg_embed,
		"avg_llm": avg_llm,
		"avg_coverage": avg_coverage,
		"scoring_mode": "asymmetric_trusted_coverage",
	}

	overall_score = compute_overall_score(field_scores)

	log.info(
		'Comparison finished in %s — overall=%.3f avg_coverage=%.3f avg_embed=%.3f avg_llm=%.3f '
		'(%d fields scored, %d ignored, %d exact matches)',
		_format_duration(time.time() - start),
		overall_score,
		avg_coverage,
		avg_embed,
		avg_llm,
		len(field_scores),
		len(ignored),
		len(report['exact_matches']),
	)

	return report, overall_score


def _format_duration(seconds):
	if seconds < 60:
		return f'{seconds:.1f}s'
	minutes, secs = divmod(int(seconds), 60)
	if minutes < 60:
		return f'{minutes}m {secs}s'
	hours, minutes = divmod(minutes, 60)
	return f'{hours}h {minutes}m {secs}s'

EMBED_SCORE_WEIGHT = 0.3
LLM_SCORE_WEIGHT = 0.7

def compute_overall_score(field_scores):
	weighted_score_sum = 0.0
	weight_sum = 0.0

	for key, score in field_scores.items():
		field_weight = FIELD_WEIGHTS.get(key, 1.0)

		if field_weight == 0:
			continue

		if score["exact"] == 1:
			field_score = 1.0
		else:
			field_score = (
				EMBED_SCORE_WEIGHT * score["embedding"] + LLM_SCORE_WEIGHT * score["llm"]
			)

		weighted_score_sum += (field_weight * field_score)

		weight_sum += field_weight

	if weight_sum == 0:
		return 0.0

	return weighted_score_sum / weight_sum

def compute_average_scores(field_scores):
	total = len(field_scores)
	if total == 0:
		return 0.0, 0.0, 0.0
	
	embed_sum = 0.0
	llm_sum = 0.0
	coverage_sum = 0.0

	for score in field_scores.values():
		embed_sum += score["embedding"]
		llm_sum += score["llm"]
		coverage_sum += score["coverage"]

	return embed_sum / total, llm_sum / total, coverage_sum / total


def score_field(key, trusted, generated):
	
	scores = {
		"exact": 0,
		"coverage": 0.0,
		"embedding": 0.0,
		"llm": 0.0,
		"verbosity_length_ratio": 1.0,
		"missing": False
	}

	field_start = time.time()

	if key not in generated:
		log.warning('Field %s: missing from generated annotation', key)
		scores['missing'] = True
		return scores

	trusted_val = trusted.get(key)
	generated_val = generated.get(key)

	if is_unknown(generated_val):
		log.warning('Field %s: generated value is unknown/empty', key)
		scores['missing'] = True
		return scores

	if key == 'functional_category':
		category_score = functional_category_similarity(trusted_val, generated_val)
		if category_score is not None:
			log.info('Field %s: graph category score %.3f', key, category_score)
			scores.update({
				'exact': 1 if category_score == 1.0 else 0,
				'coverage': category_score,
				'embedding': category_score,
				'llm': category_score,
			})
			return scores
		log.info('Field %s: no graph mapping; falling back to semantic scoring', key)

	if field_values_equal(trusted_val, generated_val):
		log.info('Field %s: exact match', key)
		scores.update({
			'exact': 1,
			'coverage': 1.0,
			'embedding': 1.0,
			'llm': 1.0,
		})
		return scores

	length_ratio = verbosity_length_ratio(trusted_val, generated_val)
	scores['verbosity_length_ratio'] = round(length_ratio, 2)
	log.info(
		'Field %s: running NLI/embed scores (generated %.0fx trusted length)',
		key, length_ratio,
	)

	nli_start = time.time()
	coverage_embed = trusted_coverage_similarity(trusted_val, generated_val)
	symmetric_embed = embedded_similarity(trusted_val, generated_val)
	log.info(
		'Field %s: NLI/embed done in %.1fs — coverage=%.3f symmetric=%.3f',
		key, time.time() - nli_start, coverage_embed, symmetric_embed,
	)
	scores['coverage'] = round(coverage_embed, 3)
	scores['embedding'] = round(
		combine_similarity_scores(coverage_embed, symmetric_embed, length_ratio),
		3,
	)

	coverage_llm = llm_coverage_similarity(
		stringify_field_value(trusted_val),
		stringify_field_value(generated_val),
	)
	symmetric_llm = llm_similarity(
		f'{key}: {trusted_val}',
		f'{key}: {generated_val}',
	)
	symmetric_llm_clipped = float(max(0.0, min(1.0, symmetric_llm)))
	scores['llm'] = round(
		combine_similarity_scores(coverage_llm, symmetric_llm_clipped, length_ratio),
		3,
	)

	log.info(
		'Field %s: finished in %.1fs — coverage=%.3f embed=%.3f llm=%.3f',
		key, time.time() - field_start,
		scores['coverage'], scores['embedding'], scores['llm'],
	)

	return scores

