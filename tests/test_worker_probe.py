from worker import probe


def test_probe_cpu_and_ram(monkeypatch):
    class FakeMem:
        total = 32 * (1024 ** 3)
        available = 20 * (1024 ** 3)

    monkeypatch.setattr(probe.psutil, "virtual_memory", lambda: FakeMem)
    monkeypatch.setattr(probe.psutil, "cpu_count", lambda logical=False: 6 if not logical else 12)
    spec = probe.probe_system()
    assert spec.cpu_physical == 6
    assert spec.cpu_logical == 12
    assert spec.system_ram_bytes == 32 * (1024 ** 3)


def test_probe_gpu_parses_nvidia_smi(monkeypatch):
    def fake_run(cmd, **kwargs):
        assert "nvidia-smi" in cmd
        return probe.subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout="0, NVIDIA RTX 2070, 8192\n",
            stderr="",
        )

    monkeypatch.setattr(probe.shutil, "which", lambda name: "/usr/bin/nvidia-smi" if name == "nvidia-smi" else None)
    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    spec = probe.probe_system()
    assert spec.gpu_count == 1
    assert spec.vram_bytes == [8192 * 1024 * 1024]
