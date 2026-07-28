from goresolve.cli import parse_args, result_to_jsonable


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
