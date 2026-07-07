#!/usr/bin/env python3
"""Observe host memory while a real coordinator annotation job runs."""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

GIB = 1024 ** 3
DEFAULT_SAFETY_FACTOR = 0.20


@dataclass
class MemoryLogSampler:
    log_path: Path
    interval_sec: float = 2.0
    _thread: threading.Thread | None = None
    _stop: threading.Event | None = None

    def start(self) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._stop = threading.Event()

        def _loop() -> None:
            with self.log_path.open("a", encoding="utf-8") as fh:
                while not self._stop.is_set():
                    ts = datetime.now(timezone.utc).isoformat()
                    fh.write(f"\n=== {ts} ===\n")
                    fh.flush()
                    for cmd in (["free", "-b"], ["free", "-h"]):
                        try:
                            out = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
                        except (OSError, subprocess.CalledProcessError) as exc:
                            out = f"<error running {cmd}: {exc}>\n"
                        fh.write(out)
                        if not out.endswith("\n"):
                            fh.write("\n")
                        fh.flush()
                    self._stop.wait(self.interval_sec)

        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._stop is not None:
            self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval_sec + 5)


def parse_memory_log(log_path: Path) -> list[dict[str, Any]]:
    text = log_path.read_text(encoding="utf-8")
    parts = re.split(r"\n=== (.+?) ===\n", text)
    samples: list[dict[str, Any]] = []
    for i in range(1, len(parts), 2):
        timestamp = parts[i]
        block = parts[i + 1]
        for line in block.splitlines():
            if line.strip().startswith("Mem:"):
                parsed = parse_free_b_mem_line(line)
                if parsed is not None:
                    samples.append({"timestamp": timestamp, **parsed})
                break
    return samples


def parse_free_b_mem_line(line: str) -> dict[str, int] | None:
    """Parse the Mem: row from `free -b` output."""
    if not line.strip().startswith("Mem:"):
        return None
    parts = line.split()
    if len(parts) < 7:
        return None
    return {
        "total_bytes": int(parts[1]),
        "used_bytes": int(parts[2]),
        "free_bytes": int(parts[3]),
        "shared_bytes": int(parts[4]),
        "buff_cache_bytes": int(parts[5]),
        "available_bytes": int(parts[6]),
    }


def percentile(values: list[int], pct: float) -> int:
    if not values:
        raise ValueError("empty values")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (pct / 100.0)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    weight = rank - low
    return int(ordered[low] * (1 - weight) + ordered[high] * weight)


def summarize_bytes(values: list[int]) -> dict[str, int | float]:
    return {
        "min": min(values),
        "max": max(values),
        "mean": int(statistics.mean(values)),
        "stdev": int(statistics.pstdev(values)) if len(values) > 1 else 0,
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
    }


def recommend_job_memory_gb(peak_incremental_bytes: int, *, safety_factor: float) -> int:
    raw_gb = (peak_incremental_bytes * (1.0 + safety_factor)) / GIB
    return int(-(-raw_gb // 1))  # ceil to whole GB


def preflight(coordinator_url: str, token: str) -> dict:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with httpx.Client(base_url=coordinator_url, headers=headers, timeout=30.0) as client:
        health = client.get("/health").json()
        if health.get("status") != "ok":
            raise RuntimeError(f"Coordinator unhealthy: {health}")
        workers = health.get("workers", {})
        if workers.get("connected", 0) < 1:
            raise RuntimeError("No workers connected; start a worker before profiling.")
        if workers.get("total_slots", 0) < 1:
            raise RuntimeError("Workers have 0 slots; increase ANNOTATION_MEMORY_BUDGET_GB.")
        annotations = health.get("stores", {}).get("annotations", {})
        if annotations.get("status") not in ("ok", "available"):
            raise RuntimeError(
                "Mongo annotation store unavailable; set MONGO_URI on the coordinator."
            )
        return health


def submit_job(client: httpx.Client, *, profile: str, locus: str) -> str:
    payload = {
        "profile": profile,
        "locus": locus,
        "allow_online_name_lookup": False,
        "allow_ortholog_fallback": True,
    }
    resp = client.post("/jobs", json=payload)
    resp.raise_for_status()
    body = resp.json()
    job_id = body.get("job_id") or body.get("id")
    if not job_id:
        raise RuntimeError(f"Unexpected /jobs response (no job_id): {body}")
    return job_id


def poll_job(
    client: httpx.Client,
    job_id: str,
    poll_interval: float = 10.0,
    *,
    log_progress: bool = True,
) -> dict:
    last_status = None
    while True:
        job = client.get(f"/jobs/{job_id}").json()
        status = job.get("status")
        step = job.get("current_step")
        if log_progress and (status, step) != last_status:
            print(f"  job {job_id}: status={status} step={step}", flush=True)
            last_status = (status, step)
        if status in ("completed", "failed"):
            return job
        time.sleep(poll_interval)


def verify_annotation_saved(client: httpx.Client, profile: str, locus: str) -> dict | None:
    annotation_id = f"{profile}:{locus}"
    resp = client.get(f"/annotations/{annotation_id}")
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def build_report(
    *,
    samples: list[dict[str, Any]],
    baseline_samples: int,
    job: dict,
    safety_factor: float,
    profile: str,
    locus: str,
) -> dict[str, Any]:
    if len(samples) < baseline_samples + 1:
        raise RuntimeError("Not enough memory samples collected.")

    baseline_used = [s["used_bytes"] for s in samples[:baseline_samples]]
    baseline_mean = int(statistics.mean(baseline_used))

    used_series = [s["used_bytes"] for s in samples]
    incremental = [max(0, u - baseline_mean) for u in used_series]
    used_stats = summarize_bytes(used_series)
    incr_stats = summarize_bytes(incremental)

    peak_incremental = incr_stats["max"]
    recommended_gb = recommend_job_memory_gb(peak_incremental, safety_factor=safety_factor)

    ortholog_ran = None
    result = job.get("result") or {}
    annotation = result.get("annotation") or {}
    meta = annotation.get("annotation_metadata") or {}
    ortholog_pass = meta.get("ortholog_pass")
    if isinstance(ortholog_pass, dict):
        ortholog_ran = ortholog_pass.get("ran")

    return {
        "profile": profile,
        "locus": locus,
        "job_id": job.get("id") or job.get("job_id"),
        "job_status": job.get("status"),
        "job_error": job.get("error"),
        "job_current_step": job.get("current_step"),
        "ortholog_pass_ran": ortholog_ran,
        "sample_count": len(samples),
        "baseline_used_bytes": baseline_mean,
        "system_used_bytes": used_stats,
        "incremental_used_bytes": incr_stats,
        "peak_incremental_bytes": peak_incremental,
        "safety_factor": safety_factor,
        "recommended_job_memory_gb": recommended_gb,
    }


def write_artifacts(
    out_dir: Path,
    *,
    samples: list[dict[str, Any]],
    report: dict[str, Any],
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out_dir / "samples.json").write_text(json.dumps(samples, indent=2), encoding="utf-8")
    text = format_report_text(report)
    (out_dir / "report.txt").write_text(text, encoding="utf-8")
    return out_dir


def format_report_text(report: dict[str, Any]) -> str:
    def gb(x: int) -> str:
        return f"{x / GIB:.1f} GB"

    incr = report["incremental_used_bytes"]
    lines = [
        "=" * 64,
        "Gene Autoannotator — Observational Job Memory Profile",
        "=" * 64,
        f"Profile / locus:  {report['profile']} / {report['locus']}",
        f"Job ID:           {report['job_id']}",
        f"Job status:       {report['job_status']}",
        f"Job error:        {report.get('job_error') or '(none)'}",
        f"Ortholog pass ran:{report['ortholog_pass_ran']}",
        f"Samples:          {report['sample_count']}",
        "",
        "Incremental memory (above baseline):",
        f"  min:  {gb(incr['min'])}",
        f"  mean: {gb(incr['mean'])}",
        f"  p95:  {gb(incr['p95'])}",
        f"  p99:  {gb(incr['p99'])}",
        f"  max:  {gb(incr['max'])}  ← peak",
        "",
        f"Safety margin:              {int(report['safety_factor'] * 100)}%",
        f"Recommended job allocation: {report['recommended_job_memory_gb']} GB",
    ]
    if report.get("job_status") == "failed":
        lines.extend([
            "",
            "Note: Job failed but memory samples above are still valid for sizing.",
        ])
    lines.append("=" * 64)
    return "\n".join(lines)


def recover_report(
    *,
    log_path: Path,
    out_dir: Path | None,
    baseline_samples: int,
    safety_factor: float,
    profile: str,
    locus: str,
    coordinator_url: str,
    token: str,
    job_id: str | None,
) -> tuple[Path, dict[str, Any], int]:
    """Build a report from an existing memory.log (e.g. after a failed run)."""
    if not log_path.is_file():
        raise FileNotFoundError(f"Memory log not found: {log_path}")

    job: dict[str, Any] = {"id": job_id, "status": "unknown"}
    if job_id:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        with httpx.Client(base_url=coordinator_url, headers=headers, timeout=30.0) as client:
            resp = client.get(f"/jobs/{job_id}")
            if resp.status_code == 200:
                job = resp.json()

    samples = parse_memory_log(log_path)
    report = build_report(
        samples=samples,
        baseline_samples=baseline_samples,
        job=job,
        safety_factor=safety_factor,
        profile=profile,
        locus=locus,
    )
    report["mongo_verified"] = False
    report["recovered_from_log"] = str(log_path)

    dest = out_dir or log_path.parent
    write_artifacts(dest, samples=samples, report=report)
    exit_code = 0 if job.get("status") == "completed" else 1
    return dest, report, exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coordinator-url", default="http://127.0.0.1:8000")
    parser.add_argument("--token", default=os.getenv("WORKER_API_TOKEN", ""))
    parser.add_argument("--profile", default="mtb-h37rv")
    parser.add_argument(
        "--locus",
        default="Rv1734c",
        help="Gene locus (default test gene; should trigger ortholog pass)",
    )
    parser.add_argument("--interval-sec", type=float, default=2.0)
    parser.add_argument(
        "--baseline-sec",
        type=float,
        default=10.0,
        help="Seconds to sample before submitting the job",
    )
    parser.add_argument("--safety-factor", type=float, default=DEFAULT_SAFETY_FACTOR)
    parser.add_argument("--output-dir", default=".cache/memory_profiles")
    parser.add_argument(
        "--recover-log",
        type=Path,
        help="Rebuild report from an existing memory.log (skip job submission)",
    )
    parser.add_argument(
        "--job-id",
        help="Job ID to attach when using --recover-log",
    )
    args = parser.parse_args(argv)

    baseline_samples = max(1, int(args.baseline_sec / args.interval_sec))

    if args.recover_log is not None:
        out_dir, report, exit_code = recover_report(
            log_path=args.recover_log,
            out_dir=args.recover_log.parent,
            baseline_samples=baseline_samples,
            safety_factor=args.safety_factor,
            profile=args.profile,
            locus=args.locus,
            coordinator_url=args.coordinator_url,
            token=args.token,
            job_id=args.job_id,
        )
        print(format_report_text(report))
        print(f"\nArtifacts: {out_dir}")
        return exit_code

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.output_dir) / run_id
    log_path = out_dir / "memory.log"

    preflight(args.coordinator_url, args.token)

    job: dict = {}
    saved: dict | None = None
    job_failed = False
    job_error: str | None = None

    sampler = MemoryLogSampler(log_path=log_path, interval_sec=args.interval_sec)
    sampler.start()
    try:
        time.sleep(args.baseline_sec)

        headers = {"Authorization": f"Bearer {args.token}"} if args.token else {}
        with httpx.Client(base_url=args.coordinator_url, headers=headers, timeout=30.0) as client:
            job_id = submit_job(client, profile=args.profile, locus=args.locus)
            print(f"Submitted job {job_id}; sampling memory...", flush=True)
            job = poll_job(client, job_id)
            if job.get("status") != "completed":
                job_failed = True
                job_error = job.get("error") or "unknown error"
            else:
                saved = verify_annotation_saved(client, args.profile, args.locus)
                if saved is None:
                    print(
                        "Warning: job completed but annotation not found in Mongo.",
                        file=sys.stderr,
                    )
    finally:
        sampler.stop()

    samples = parse_memory_log(log_path)
    report = build_report(
        samples=samples,
        baseline_samples=baseline_samples,
        job=job,
        safety_factor=args.safety_factor,
        profile=args.profile,
        locus=args.locus,
    )
    report["mongo_verified"] = saved is not None
    write_artifacts(out_dir, samples=samples, report=report)
    print(format_report_text(report))
    print(f"\nArtifacts: {out_dir}")
    if job_failed:
        print(f"\nJob failed: {job_error}", file=sys.stderr)
        print("Memory report saved anyway (see report.txt).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
