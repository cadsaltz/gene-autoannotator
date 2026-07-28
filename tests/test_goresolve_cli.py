import json
from argparse import Namespace

import pytest

from goresolve.cli import _load_inputs, parse_args, result_to_jsonable


def test_parse_args_categories_and_function():
    args = parse_args([
        '--function', 'cytokinesis during mitosis',
        '--category', 'Cytokinesis',
        '--category', 'Mitosis',
        '--obo', 'tests/fixtures/go/mini.obo',
        '--model', 'm1',
        '--model', 'm2',
        '--fake-embeddings',
        '--rank-stub',
    ])
    assert args.function == 'cytokinesis during mitosis'
    assert args.category == ['Cytokinesis', 'Mitosis']


def test_result_to_jsonable_roundtrip_keys():
    from goresolve.types import GoResolutionResult

    payload = result_to_jsonable(GoResolutionResult(
        go_terms=(), method='skipped_no_text', queries=(), shortlist=(),
    ))
    assert payload['method'] == 'skipped_no_text'
    assert payload['go_terms'] == []


def test_load_inputs_from_json_rejects_malformed_json(tmp_path, capsys):
    path = tmp_path / 'bad.json'
    path.write_text('{not json', encoding='utf-8')
    args = Namespace(function=None, category=[], from_json=str(path))

    with pytest.raises(SystemExit) as exc:
        _load_inputs(args)

    assert exc.value.code == 2
    assert 'invalid JSON' in capsys.readouterr().err


def test_load_inputs_from_json_rejects_non_object_root(tmp_path, capsys):
    path = tmp_path / 'array.json'
    path.write_text(json.dumps(['function']), encoding='utf-8')
    args = Namespace(function=None, category=[], from_json=str(path))

    with pytest.raises(SystemExit) as exc:
        _load_inputs(args)

    assert exc.value.code == 2
    assert 'JSON root must be an object' in capsys.readouterr().err
