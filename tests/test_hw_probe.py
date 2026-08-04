import subprocess

from worker import hw_probe


def test_parse_nvidia_smi_csv():
    raw = "0, NVIDIA A100-SXM4-80GB, 72, 61234, 81920, 64\n"
    gpus = hw_probe.parse_nvidia_smi_csv(raw)
    assert gpus[0].index == 0
    assert gpus[0].util_percent == 72
    assert gpus[0].mem_used_mb == 61234
    assert gpus[0].mem_total_mb == 81920
    assert gpus[0].temp_c == 64
    assert gpus[0].name == "NVIDIA A100-SXM4-80GB"


def test_parse_nvidia_smi_csv_quoted_name_with_commas():
    raw = '0,"NVIDIA RTX 2070, Super",10,1000,8192,55\n'
    gpus = hw_probe.parse_nvidia_smi_csv(raw)
    assert gpus[0].name == "NVIDIA RTX 2070, Super"


def test_parse_nvidia_smi_empty_is_unavailable():
    result = hw_probe.parse_nvidia_smi_csv("")
    assert isinstance(result, hw_probe.GpuUnavailable) or result == []


def test_parse_meminfo():
    raw = "MemTotal:       503316480 kB\nMemAvailable:   102400000 kB\n"
    stat = hw_probe.parse_meminfo(raw)
    assert stat.total_bytes > stat.available_bytes
    assert stat.total_bytes == 503316480 * 1024
    assert stat.available_bytes == 102400000 * 1024
    assert stat.cpu_percent is None


def test_cpu_percent_from_proc_stat_samples():
    prev = hw_probe.ProcStatSample(idle=100, total=1000)
    curr = hw_probe.ProcStatSample(idle=150, total=1500)
    assert hw_probe.cpu_percent_from_samples(prev, curr) == 90.0


def test_probe_gpus_missing_nvidia_smi(monkeypatch):
    monkeypatch.setattr(hw_probe.shutil, "which", lambda name: None)
    result = hw_probe.probe_gpus()
    assert isinstance(result, hw_probe.GpuUnavailable)
    assert "nvidia-smi" in result.reason


def test_probe_gpus_nonzero_exit(monkeypatch):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="err")

    monkeypatch.setattr(
        hw_probe.shutil,
        "which",
        lambda name: "/usr/bin/nvidia-smi" if name == "nvidia-smi" else None,
    )
    monkeypatch.setattr(hw_probe.subprocess, "run", fake_run)
    result = hw_probe.probe_gpus()
    assert isinstance(result, hw_probe.GpuUnavailable)


def test_probe_gpus_success(monkeypatch):
    def fake_run(cmd, **kwargs):
        assert cmd[:2] == ["nvidia-smi", "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu"]
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout="0, NVIDIA A100-SXM4-80GB, 72, 61234, 81920, 64\n",
            stderr="",
        )

    monkeypatch.setattr(
        hw_probe.shutil,
        "which",
        lambda name: "/usr/bin/nvidia-smi" if name == "nvidia-smi" else None,
    )
    monkeypatch.setattr(hw_probe.subprocess, "run", fake_run)
    result = hw_probe.probe_gpus()
    assert isinstance(result, list)
    assert result[0].util_percent == 72


def test_probe_cpu_ram_reads_meminfo(tmp_path, monkeypatch):
    proc = tmp_path / "proc"
    proc.mkdir()
    (proc / "meminfo").write_text(
        "MemTotal:       503316480 kB\nMemAvailable:   102400000 kB\n",
        encoding="utf-8",
    )
    (proc / "stat").write_text("cpu  100 0 50 900 0 0 0 0 0 0\n", encoding="utf-8")
    monkeypatch.setattr(hw_probe, "_PROC_ROOT", proc)
    stat = hw_probe.probe_cpu_ram()
    assert stat.total_bytes == 503316480 * 1024
    assert stat.available_bytes == 102400000 * 1024
    assert stat.cpu_percent is None


def test_probe_cpu_ram_with_previous_sample(tmp_path, monkeypatch):
    proc = tmp_path / "proc"
    proc.mkdir()
    (proc / "meminfo").write_text(
        "MemTotal:       503316480 kB\nMemAvailable:   102400000 kB\n",
        encoding="utf-8",
    )
    (proc / "stat").write_text("cpu  200 0 0 1000 0 0 0 0 0 0\n", encoding="utf-8")
    monkeypatch.setattr(hw_probe, "_PROC_ROOT", proc)
    prev = hw_probe.ProcStatSample(idle=900, total=1000)
    stat = hw_probe.probe_cpu_ram(prev_stat_sample=prev)
    assert stat.cpu_percent == 50.0


def test_ollama_cpu_from_samples_uses_top_style_percent():
    prev = hw_probe.OllamaCpuSample(jiffies=1000, process_count=2, monotonic=0.0)
    curr = hw_probe.OllamaCpuSample(jiffies=1000 + 200, process_count=2, monotonic=1.0)
    stat = hw_probe.ollama_cpu_from_samples(prev, curr)
    assert stat is not None
    assert stat.percent == 200.0
    assert stat.cores == 2.0
    assert stat.process_count == 2


def test_read_ollama_cpu_sample_sums_matching_procs(tmp_path, monkeypatch):
    proc = tmp_path / "proc"
    proc.mkdir()
    (proc / "1").mkdir()
    (proc / "1" / "comm").write_text("ollama\n", encoding="utf-8")
    (proc / "1" / "stat").write_text("1 (ollama) S 0 0 0 0 0 0 0 0 0 0 1000 200\n", encoding="utf-8")
    (proc / "2").mkdir()
    (proc / "2" / "comm").write_text("python\n", encoding="utf-8")
    (proc / "999").mkdir()
    (proc / "999" / "comm").write_text("ollama\n", encoding="utf-8")
    (proc / "999" / "stat").write_text("999 (ollama) S 0 0 0 0 0 0 0 0 0 0 50 25\n", encoding="utf-8")
    (proc / "770513").mkdir()
    (proc / "770513" / "comm").write_text("llama-server\n", encoding="utf-8")
    (proc / "770513" / "stat").write_text(
        "770513 (llama-server) R 0 0 0 0 0 0 0 0 0 0 300 100\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(hw_probe, "_PROC_ROOT", proc)
    sample = hw_probe.read_ollama_cpu_sample()
    assert sample.process_count == 3
    assert sample.jiffies == 1675


def test_probe_ollama_cpu_first_tick_is_none_second_computes(tmp_path, monkeypatch):
    proc = tmp_path / "proc"
    proc.mkdir()
    (proc / "42").mkdir()
    (proc / "42" / "comm").write_text("ollama\n", encoding="utf-8")
    (proc / "42" / "stat").write_text("42 (ollama) S 0 0 0 0 0 0 0 0 0 0 0 0\n", encoding="utf-8")
    monkeypatch.setattr(hw_probe, "_PROC_ROOT", proc)

    stat0, sample0 = hw_probe.probe_ollama_cpu()
    assert stat0 is None
    assert sample0.process_count == 1

    (proc / "42" / "stat").write_text("42 (ollama) R 0 0 0 0 0 0 0 0 0 0 100 50\n", encoding="utf-8")
    monkeypatch.setattr(hw_probe.time, "monotonic", lambda: sample0.monotonic + 1.0)
    stat1, _ = hw_probe.probe_ollama_cpu(prev_sample=sample0)
    assert stat1 is not None
    assert stat1.percent == 150.0
    assert stat1.cores == 1.5


def test_probe_ollama_cpu_percent_returns_none_or_float():
    stat, sample = hw_probe.probe_ollama_cpu()
    assert stat is None
    assert isinstance(sample, hw_probe.OllamaCpuSample)
