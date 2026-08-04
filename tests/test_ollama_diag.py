from __future__ import annotations

from worker.fleet.ollama_diag import format_summary_lines, summarize_ollama_lines


SAMPLE_LOG = """
time=2026-08-04T08:30:00.924-07:00 level=INFO source=llama_server.go:614 msg="disabling multimodal projector offload" reason=limited-vram
time=2026-08-04T08:30:00.924-07:00 level=INFO source=llama_server.go:889 msg="loading model via llama-server"
common_params_fit_impl: cannot meet free memory target of 1959 MiB, need to reduce device memory by 2821 MiB
common_fit_params: successfully fit params to free device memory
load_tensors: offloaded 31/49 layers to GPU
time=2026-08-04T08:30:12.590-07:00 level=INFO source=sched.go:739 msg="loaded runners" count=1
srv  llama_server: model loaded
srv  update_slots: all slots are idle
time=2026-08-04T08:30:12.631-07:00 level=WARN source=llama_server.go:299 msg="truncating input prompt" limit=4095 prompt=6333 keep=4 new=4095
slot launch_slot_: id  1 | task 0 | processing task, is_child = 0
slot print_timing: id  1 | task 0 | prompt processing, n_tokens =   2048, progress = 0.50
slot      release: id  1 | task 0 | stop processing: n_tokens = 4095, truncated = 1
srv  update_slots: all slots are idle
[GIN] 2026/08/04 - 08:30:23 | 200 | 24.539923483s |       127.0.0.1 | POST     "/api/chat"
[GIN] 2026/08/04 - 08:30:36 | 200 |     620.332µs |       127.0.0.1 | GET      "/api/tags"
""".strip().splitlines()


def test_summarize_user_log_excerpt():
    summary = summarize_ollama_lines(SAMPLE_LOG)
    assert summary.phase == "idle"
    assert summary.runners == 1
    assert summary.layers_on_gpu == 31
    assert summary.layers_total == 49
    assert summary.last_chat is not None
    assert summary.last_chat.status == 200
    assert 24.0 < summary.last_chat.duration_s < 25.0
    codes = {a.code for a in summary.alerts}
    assert "prompt_truncated" in codes
    assert "limited_vram" in codes
    assert "vram_fit_failed" not in codes  # cleared by later success
    truncate = next(a for a in summary.alerts if a.code == "prompt_truncated")
    assert "6333→4095" in truncate.message
    assert "parallel=1" in truncate.message


def test_summarize_ignores_tags_and_noise():
    summary = summarize_ollama_lines(
        [
            'llama_model_loader: - kv   0: gemma3.attention.head_count u32 = 16',
            'slot launch_slot_: sampler params:',
            '	top_k = 64, top_p = 0.950',
            '[GIN] 2026/08/04 - 08:30:21 | 200 |    1.037786ms |       127.0.0.1 | GET      "/api/tags"',
        ]
    )
    assert summary.last_chat is None
    assert summary.alerts == []


def test_chat_http_error_alert():
    summary = summarize_ollama_lines(
        [
            '[GIN] 2026/08/04 - 08:30:23 | 500 | 1.2s | 127.0.0.1 | POST     "/api/chat"',
        ]
    )
    assert summary.last_chat is not None
    assert summary.last_chat.status == 500
    assert any(a.code == "chat_http_error" for a in summary.alerts)


def test_exit_marker_sets_dead():
    summary = summarize_ollama_lines(
        ["*** Ollama server http://127.0.0.1:11434 exited unexpectedly (code=1) ***"]
    )
    assert summary.phase == "dead"
    assert any(a.code == "exited" for a in summary.alerts)


def test_format_summary_lines_layout_c():
    summary = summarize_ollama_lines(SAMPLE_LOG)
    lines = format_summary_lines(summary)
    text = "\n".join(lines)
    assert "phase: idle" in text
    assert "runners=1" in text
    assert "layers 31/49 GPU" in text
    assert "last chat: 200 in 24.5s" in text
    assert "! truncating prompt 6333→4095" in text
    assert "sampler" not in text
    assert "kv" not in text.lower() or "prompt" in text  # no tokenizer kv dump
