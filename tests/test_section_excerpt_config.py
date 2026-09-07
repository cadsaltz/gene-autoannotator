import pytest
from autoannotation.section_excerpt_config import section_excerpt_config_from_env


def test_defaults_match_spec():
    cfg = section_excerpt_config_from_env({})
    assert cfg.chunking_enabled is True
    assert cfg.max_chars == 6000
    assert cfg.retrieval_threshold_chars == 20000


def test_invalid_bool_raises():
    with pytest.raises(ValueError, match="AUTOANNOTATION_SECTION_CHUNKING"):
        section_excerpt_config_from_env({"AUTOANNOTATION_SECTION_CHUNKING": "maybe"})


def test_retrieval_must_exceed_max():
    with pytest.raises(ValueError, match="retrieval"):
        section_excerpt_config_from_env({
            "AUTOANNOTATION_SECTION_EXCERPT_MAX_CHARS": "6000",
            "AUTOANNOTATION_SECTION_RETRIEVAL_THRESHOLD_CHARS": "6000",
        })
