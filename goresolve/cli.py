from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path

from goresolve.embeddings import FakeEmbedder, SentenceTransformerEmbedder
from goresolve.resolve import has_usable_text, resolve_go_terms
from goresolve.types import GoResolutionResult

DEFAULT_GO_BASIC_OBO_PATH = os.path.join('data', 'go-basic.obo')
GO_BASIC_OBO_ENV_VAR = 'GO_BASIC_OBO_PATH'
DEFAULT_RANKER_MODEL = 'qwen3:8b'
DEFAULT_EMBED_MODEL = 'sentence-transformers/all-MiniLM-L6-v2'


def build_parser() -> argparse.ArgumentParser:
    default_obo = os.environ.get(GO_BASIC_OBO_ENV_VAR, DEFAULT_GO_BASIC_OBO_PATH)
    parser = argparse.ArgumentParser(prog='goresolve')
    parser.add_argument('--function', default=None, help='Gene function text')
    parser.add_argument(
        '--category',
        action='append',
        default=[],
        metavar='TEXT',
        help='Functional category (repeatable)',
    )
    parser.add_argument(
        '--from-json',
        metavar='PATH',
        help='Read function and functional_category from an annotation JSON file',
    )
    parser.add_argument('--obo', default=default_obo, help='Path to GO OBO file')
    parser.add_argument(
        '--model',
        action='append',
        default=[],
        metavar='NAME',
        help='Ollama ranker model (repeatable)',
    )
    parser.add_argument('--top-k', type=int, default=25, help='Max embedding retrieval hits')
    parser.add_argument('--min-cosine', type=float, default=0.35, help='Min cosine for retrieval')
    parser.add_argument(
        '--fake-embeddings',
        action='store_true',
        help='Use deterministic FakeEmbedder (offline demos)',
    )
    parser.add_argument(
        '--exact-only',
        action='store_true',
        help='Skip LLM rankers; return exact/alias shortlist hits only',
    )
    parser.add_argument(
        '--embed-model',
        default=DEFAULT_EMBED_MODEL,
        help='Sentence-transformers model for retrieval embeddings',
    )
    parser.add_argument(
        '--rank-stub',
        action='store_true',
        help=argparse.SUPPRESS,
    )
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def result_to_jsonable(result: GoResolutionResult) -> dict:
    def convert(value):
        if is_dataclass(value):
            return convert(asdict(value))
        if isinstance(value, tuple):
            return [convert(item) for item in value]
        if isinstance(value, dict):
            return {key: convert(item) for key, item in value.items()}
        if isinstance(value, list):
            return [convert(item) for item in value]
        return value

    return convert(result)


def _normalize_categories(value) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else None
    if isinstance(value, list):
        categories = [
            item.strip()
            for item in value
            if isinstance(item, str) and item.strip()
        ]
        return categories or None
    return None


def _load_inputs(args: argparse.Namespace) -> tuple[str | None, list[str] | None]:
    function = args.function
    categories = list(args.category) if args.category else None

    if args.from_json:
        path = Path(args.from_json)
        if not path.is_file():
            print(f'error: JSON file not found: {path}', file=sys.stderr)
            raise SystemExit(2)
        try:
            with path.open(encoding='utf-8') as handle:
                payload = json.load(handle)
        except json.JSONDecodeError as exc:
            print(f'error: invalid JSON in {path}: {exc}', file=sys.stderr)
            raise SystemExit(2) from exc
        if not isinstance(payload, dict):
            print(
                f'error: JSON root must be an object, got {type(payload).__name__}',
                file=sys.stderr,
            )
            raise SystemExit(2)
        if function is None:
            raw_function = payload.get('function')
            function = raw_function.strip() if isinstance(raw_function, str) else None
        if categories is None:
            categories = _normalize_categories(payload.get('functional_category'))

    if categories == []:
        categories = None
    return function, categories


def _build_embedder(args: argparse.Namespace):
    if args.fake_embeddings:
        return FakeEmbedder(dim=64)
    return SentenceTransformerEmbedder(model_name=args.embed_model)


def _ranker_models(args: argparse.Namespace) -> list[str]:
    if args.exact_only or args.rank_stub:
        return []
    if args.model:
        return list(args.model)
    return [DEFAULT_RANKER_MODEL]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    obo_path = Path(args.obo)
    if not obo_path.is_file():
        print(f'error: OBO file not found: {obo_path}', file=sys.stderr)
        return 2

    function, categories = _load_inputs(args)
    embedder = _build_embedder(args) if has_usable_text(function, categories) else None
    result = resolve_go_terms(
        function=function,
        functional_category=categories,
        ontology_path=str(obo_path),
        embedder=embedder,
        ranker_models=_ranker_models(args),
        top_k=args.top_k,
        min_cosine=args.min_cosine,
    )
    print(json.dumps(result_to_jsonable(result), indent=2, sort_keys=True))
    return 0
