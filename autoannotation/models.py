import os


# autoannotation/models.py

# Model roles are deliberately separated: summary models create independent
# section candidates, a consensus model reconciles each section, and an
# aggregation model synthesizes across papers. Two or more summary models are
# supported; the default performance stack uses three extractors from different
# families. Consensus requires ceil(n/2) agreement among those extractors.
# === Performance models ===
PERF_MODELS = {
    'summary': ['qwen3:14b', 'gemma3:12b', 'mistral-nemo:12b'],
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
    if len(models) < 2:
        raise ValueError('AUTOANNOTATION_SUMMARY_MODELS must contain at least two models')
    return models


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
# Regex generation reuses the reconciliation-strength model by default because
# it must produce a single, well-formed pattern rather than creative prose.
MODEL_REGEX = os.getenv('AUTOANNOTATION_REGEX_MODEL') or MODEL_CONSENSUS
