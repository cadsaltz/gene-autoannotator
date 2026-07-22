# autoannotation/models.py

# === Performance models ===
PERF_MODELS = {
    'summary': ['mistral-nemo:12b','llama3:8b','gemma3:12b'],
    'consensus': 'phi4:14b',
    'aggregation': 'gemma3:12b'
}

# === Lite models (<3GB each) ===
# Use smaller, RAM-friendly alternatives that roughly mimic variety:
LITE_MODELS = {
    'summary': ['mistral:7b-instruct-v0.2-q3_K_M', 'llama3.2:3b', 'gemma3:4b'],
    'consensus': 'phi3:3.8b',
    'aggregation': 'gemma3:4b'
}

# === Select mode ===
MODE = 'performance'   # 'performance' or 'lite'

if MODE == 'performance':
    MODEL_SUMMARY = PERF_MODELS['summary']
    MODEL_CONSENSUS = PERF_MODELS['consensus']
    MODEL_AGGREGATION = PERF_MODELS['aggregation']
else:
    MODEL_SUMMARY = LITE_MODELS['summary']
    MODEL_CONSENSUS = LITE_MODELS['consensus']
    MODEL_AGGREGATION = LITE_MODELS['aggregation']