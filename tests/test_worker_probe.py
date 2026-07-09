import psutil

from worker import probe


def _mock_no_gpu(monkeypatch):
    monkeypatch.setattr(probe.shutil, "which", lambda name: None)


def test_probe_cpu_and_ram(monkeypatch):
    class FakeMem:
        total = 32 * (1024 ** 3)
        available = 20 * (1024 ** 3)

    _mock_no_gpu(monkeypatch)
    monkeypatch.setattr(psutil, "virtual_memory", lambda: FakeMem)
    monkeypatch.setattr(psutil, "cpu_count", lambda logical=False: 6 if not logical else 12)
    spec = probe.probe_system()
    assert spec.cpu_physical == 6
    assert spec.cpu_logical == 12
    assert spec.system_ram_bytes == 32 * (1024 ** 3)
    assert spec.gpu_count == 0


def test_probe_psutil_failure_fallbacks(monkeypatch):
    _mock_no_gpu(monkeypatch)

    def broken_virtual_memory():
        raise RuntimeError("psutil unavailable")

    monkeypatch.setattr(psutil, "virtual_memory", broken_virtual_memory)
    monkeypatch.setattr(psutil, "cpu_count", lambda logical=False: (_ for _ in ()).throw(RuntimeError("psutil unavailable")))
    spec = probe.probe_system()
    assert spec.system_ram_bytes == 0
    assert spec.cpu_physical == 1
    assert spec.cpu_logical == 1


def test_probe_no_nvidia_smi(monkeypatch):
    _mock_no_gpu(monkeypatch)
    spec = probe.probe_system()
    assert spec.gpu_count == 0
    assert spec.vram_bytes == ()


def test_probe_nvidia_smi_nonzero_exit(monkeypatch):
    def fake_run(cmd, **kwargs):
        return probe.subprocess.CompletedProcess(
            args=cmd,
            returncode=1,
            stdout="",
            stderr="driver error",
        )

    monkeypatch.setattr(
        probe.shutil,
        "which",
        lambda name: "/usr/bin/nvidia-smi" if name == "nvidia-smi" else None,
    )
    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    spec = probe.probe_system()
    assert spec.gpu_count == 0
    assert spec.vram_bytes == ()


def test_probe_gpu_parses_nvidia_smi(monkeypatch):
    def fake_run(cmd, **kwargs):
        assert "nvidia-smi" in cmd
        return probe.subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout="0, NVIDIA RTX 2070, 8192\n",
            stderr="",
        )

    monkeypatch.setattr(
        probe.shutil,
        "which",
        lambda name: "/usr/bin/nvidia-smi" if name == "nvidia-smi" else None,
    )
    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    spec = probe.probe_system()
    assert spec.gpu_count == 1
    assert spec.vram_bytes == (8192 * 1024 * 1024,)


def test_probe_gpu_name_with_commas(monkeypatch):
    def fake_run(cmd, **kwargs):
        return probe.subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout='0, "NVIDIA RTX 2070, Super", 8192\n',
            stderr="",
        )

    monkeypatch.setattr(
        probe.shutil,
        "which",
        lambda name: "/usr/bin/nvidia-smi" if name == "nvidia-smi" else None,
    )
    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    spec = probe.probe_system()
    assert spec.gpu_count == 1
    assert spec.vram_bytes == (8192 * 1024 * 1024,)


def test_probe_multiple_gpus(monkeypatch):
    def fake_run(cmd, **kwargs):
        return probe.subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout="0, GPU A, 8192\n1, GPU B, 16384\nbad-line\n",
            stderr="",
        )

    monkeypatch.setattr(
        probe.shutil,
        "which",
        lambda name: "/usr/bin/nvidia-smi" if name == "nvidia-smi" else None,
    )
    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    spec = probe.probe_system()
    assert spec.gpu_count == 2
    assert spec.vram_bytes == (8192 * 1024 * 1024, 16384 * 1024 * 1024)


def test_vram_total_bytes():
    spec = probe.SystemSpec(
        gpu_count=2,
        vram_bytes=(1000, 2000),
        system_ram_bytes=0,
        cpu_physical=1,
        cpu_logical=1,
    )
    assert spec.vram_total_bytes == 3000
