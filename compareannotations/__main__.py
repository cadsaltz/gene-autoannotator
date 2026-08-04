import argparse
import json
import logging
import sys
import time

from . import core

log = logging.getLogger(__name__)


def configure_logging(verbose=False):
	level = logging.DEBUG if verbose else logging.INFO
	logging.basicConfig(
		format='%(asctime)s %(levelname).1s | %(message)s',
		level=level,
		force=True,
	)
	# Keep third-party libraries quieter during long model loads.
	for noisy in ('httpx', 'httpcore', 'transformers', 'sentence_transformers', 'urllib3'):
		logging.getLogger(noisy).setLevel(logging.WARNING)


def main(trusted, generated, verbose=False):
	configure_logging(verbose=verbose)

	log.info('Comparing trusted=%s', trusted)
	log.info('Comparing generated=%s', generated)

	load_start = time.time()
	trusted_data = core.load_json(trusted)
	generated_data = core.load_json(generated)
	log.info('Loaded JSON files (%.1fs)', time.time() - load_start)

	report, score = core.compare(trusted_data, generated_data)

	print('\n=== TRUSTED ANNOTATION ===\n')
	print(json.dumps(report['trusted'], indent=2))

	print('\n=== GENERATED ANNOTATION ===\n')
	print(json.dumps(report['generated'], indent=2))

	print('\n=== COMPARISON REPORT ===\n')

	print(f'{len(report["trusted"])}\t: fields in trusted')
	print(f'{len(report["generated"])}\t: fields in generated')
	print(f'{len(report["ignored"])}\t: ignored fields')
	print(f'{len(report["exact_matches"])}\t: exact field matches')

	non_exact = len(report['field_scores']) - len(report['exact_matches'])
	print(f'{non_exact}\t: non-exact field Matches')

	print(f'{report["avg_embed"]:.2f}\t: AVG embed score')
	print(f'{report["avg_llm"]:.2f}\t: AVG llm score')
	print(f'{report.get("avg_coverage", 0):.2f}\t: AVG trusted-coverage score')
	print(f'{report.get("scoring_mode", "legacy")}\t: scoring mode')

	print(f'{len(report["missing"])}\t: missing fields')
	print(f'{len(report["extra"])}\t: extra fields')

	print('\n=== FIELD SCORES ===\n')

	for field, scores in report['field_scores'].items():
		combined = (scores['embedding'] + scores['llm']) / 2
		coverage = scores.get('coverage', 0.0)
		verbosity = scores.get('verbosity_length_ratio', 1.0)
		print(
			f'combined: {combined:.2f} coverage: {coverage:.2f} exact: {scores["exact"]} '
			f'embed: {scores["embedding"]:.2f} llm: {scores["llm"]:.2f} '
			f'len_ratio: {verbosity:.1f}\t: {field}'
		)

	print(f'\nOverall Score: {score:.2f}\n')

	print('\n=== END OF REPORT ===\n')

	log.info('Overall comparison score: %.3f', score)
	return score


if __name__ == '__main__':
	parser = argparse.ArgumentParser(
		description='Compare gene annotations',
	)
	parser.add_argument('trusted', help='Path to trusted JSON annotation')
	parser.add_argument('generated', help='Path to generated JSON annotation')
	parser.add_argument(
		'-v', '--verbose',
		action='store_true',
		help='Enable debug logging (per-step detail)',
	)

	args = parser.parse_args(sys.argv[1:])
	main(trusted=args.trusted, generated=args.generated, verbose=args.verbose)
