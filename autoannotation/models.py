import os


# autoannotation/models.py

# Model roles are deliberately separated: summary models extract each section,
# an optional consensus model reconciles multiple extractors, and an
# aggregation model synthesizes across papers.
#
# Production performance extraction is a single model (gemma4:12b). With one
# extractor, section consensus is skipped and the extractor JSON is used as
# the section distillation. Lite/nano keep a multi-extractor stack for
# infrastructure tests; AUTOANNOTATION_SUMMARY_MODELS can restore a crowd.
# === Performance models ===
PERF_MODELS = {
    'summary': ['gemma4:12b'],
    'consensus': 'qwen3:8b',
    'aggregation': 'gemma3:27b',
}

# === Lite models (~4GB total) ===
# Use smaller, RAM-friendly alternatives that roughly mimic variety:
LITE_MODELS = {
    'summary': ['qwen3.5:0.8b', 'gemma3:1b', 'llama3.2:1b'],
    'consensus': 'qwen3:0.6b',
    'aggregation': 'qwen3:1.7b',
}

# === Nano models (~2GB total on GPU) ===
# Infrastructure / router testing on ~8GB VRAM: two homogeneous Ollama servers
# can each keep all four models warm. Not for production annotation quality.
NANO_MODELS = {
    'summary': ['qwen3:0.6b', 'qwen2.5:0.5b', 'gemma3:270m'],
    'consensus': 'gemma3:270m',
    'aggregation': 'gemma3:1b',
}


def _parse_summary_models(value):
    if not value:
        return None
    models = [item.strip() for item in value.split(',') if item.strip()]
    if not models:
        return None
    return models


def uses_section_consensus(summary_models=None):
    """Consensus runs only when two or more extractors produced candidates."""
    names = MODEL_SUMMARY if summary_models is None else summary_models
    return len(names) >= 2


def section_distillation_model_name(summary_models=None, consensus_model=None):
    """Model tag recorded on the section-distillation row."""
    names = MODEL_SUMMARY if summary_models is None else summary_models
    consensus = MODEL_CONSENSUS if consensus_model is None else consensus_model
    if len(names) == 1:
        return names[0]
    return consensus


def _select_model_set(mode):
    normalized_mode = mode.strip().lower()
    if normalized_mode == 'performance':
        return PERF_MODELS
    if normalized_mode == 'lite':
        return LITE_MODELS
    if normalized_mode == 'nano':
        return NANO_MODELS
    raise ValueError(
        "AUTOANNOTATION_MODEL_MODE must be 'performance', 'lite', or 'nano'"
    )


# === Select mode ===
MODE = os.getenv('AUTOANNOTATION_MODEL_MODE', 'performance')
MODEL_SET = _select_model_set(MODE)

MODEL_SUMMARY = (
    _parse_summary_models(os.getenv('AUTOANNOTATION_SUMMARY_MODELS'))
    or MODEL_SET['summary']
)
MODEL_CONSENSUS = os.getenv('AUTOANNOTATION_CONSENSUS_MODEL') or MODEL_SET['consensus']
MODEL_AGGREGATION = os.getenv('AUTOANNOTATION_AGGREGATION_MODEL') or MODEL_SET['aggregation']
# Regex generation prefers the extractor when production is single-model so
# Ollama does not pull an unused consensus tag. Multi-extractor modes still
# reuse the reconciliation-strength model.
MODEL_REGEX = (
    os.getenv('AUTOANNOTATION_REGEX_MODEL')
    or (MODEL_SUMMARY[0] if not uses_section_consensus() else MODEL_CONSENSUS)
)
