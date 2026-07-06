"""Manual benchmark for Ollama model-switching overhead in annotation inference.

This script is intentionally isolated from the production pipeline. It imports
the same paper retrieval and LLM inference helpers, but bypasses only this
benchmark run's LLM response cache so each request makes a real Ollama call.

Example:
    python tests/benchmark_ollama_model_switching.py --profile mtb-h37rv --locus Rv0001
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


NANOSECONDS_PER_SECOND = 1_000_000_000
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
DEFAULT_GENE_NAME_CACHE_DIR = os.path.join(".cache", "gene_names")
OLLAMA_DURATION_FIELDS = (
    "total_duration",
    "load_duration",
    "prompt_eval_duration",
    "eval_duration",
)
OLLAMA_COUNT_FIELDS = (
    "prompt_eval_count",
    "eval_count",
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def round_or_none(value: float | int | None, digits: int = 3) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def percent_reduction(old_value: float | int | None, new_value: float | int | None) -> float | None:
    if old_value in (None, 0) or new_value is None:
        return None
    return round((float(old_value) - float(new_value)) / float(old_value) * 100.0, 1)


def response_get(response: Any, key: str, default: Any = None) -> Any:
    if isinstance(response, dict):
        return response.get(key, default)
    if hasattr(response, key):
        return getattr(response, key)
    try:
        return response[key]
    except Exception:
        return default


def make_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): make_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [make_jsonable(item) for item in value]
    if hasattr(value, "model_dump"):
        return make_jsonable(value.model_dump())
    if hasattr(value, "dict"):
        return make_jsonable(value.dict())
    return str(value)


def ollama_metrics_from_response(response: Any | None) -> dict[str, Any]:
    if response is None:
        return {}
    metrics: dict[str, Any] = {}
    for field in OLLAMA_DURATION_FIELDS:
        raw_value = response_get(response, field)
        metrics[f"{field}_sec"] = (
            raw_value / NANOSECONDS_PER_SECOND if raw_value is not None else None
        )
    for field in OLLAMA_COUNT_FIELDS:
        metrics[field] = response_get(response, field)
    return metrics


def sum_known(values: list[float | int | None]) -> float | None:
    known = [float(value) for value in values if value is not None]
    if not known:
        return None
    return round(sum(known), 3)


def estimate_switch_overhead_from_request_durations(requests: list[dict[str, Any]]) -> float:
    non_switch_durations_by_model: dict[str, list[float]] = defaultdict(list)
    all_durations_by_model: dict[str, list[float]] = defaultdict(list)
    for request in requests:
        model_name = request["model_name"]
        duration = float(request["duration_sec"])
        all_durations_by_model[model_name].append(duration)
        if not request.get("model_switched"):
            non_switch_durations_by_model[model_name].append(duration)

    overhead = 0.0
    for request in requests:
        if not request.get("model_switched"):
            continue
        model_name = request["model_name"]
        baseline_candidates = (
            non_switch_durations_by_model.get(model_name)
            or all_durations_by_model.get(model_name)
            or []
        )
        if not baseline_candidates:
            continue
        baseline = statistics.median(baseline_candidates)
        overhead += max(0.0, float(request["duration_sec"]) - baseline)
    return round(overhead, 3)


def summarize_strategy(
    strategy_name: str,
    total_runtime_sec: float,
    requests: list[dict[str, Any]],
    transitions: list[dict[str, Any]],
    memory_samples: list[dict[str, Any]],
) -> dict[str, Any]:
    per_model_runtime: dict[str, float] = defaultdict(float)
    for request in requests:
        per_model_runtime[request["model_name"]] += float(request["duration_sec"])

    load_durations = [
        request.get("ollama_metrics", {}).get("load_duration_sec")
        for request in requests
    ]
    eval_durations = [
        request.get("ollama_metrics", {}).get("eval_duration_sec")
        for request in requests
    ]
    prompt_eval_durations = [
        request.get("ollama_metrics", {}).get("prompt_eval_duration_sec")
        for request in requests
    ]
    switched_load_durations = [
        request.get("ollama_metrics", {}).get("load_duration_sec")
        for request in requests
        if request.get("model_switched")
    ]

    total_load_time = sum_known(load_durations)
    total_generation_time = sum_known(eval_durations)
    total_prompt_eval_time = sum_known(prompt_eval_durations)
    switch_load_time = sum_known(switched_load_durations)
    if switch_load_time is not None:
        switch_overhead = switch_load_time
        switch_overhead_method = "ollama_load_duration_on_switches"
    else:
        switch_overhead = estimate_switch_overhead_from_request_durations(requests)
        switch_overhead_method = "estimated_switch_request_excess"

    process_peaks = [
        sample.get("process_rss_bytes") for sample in memory_samples
        if sample.get("process_rss_bytes") is not None
    ]
    system_peaks = [
        sample.get("system_used_bytes") for sample in memory_samples
        if sample.get("system_used_bytes") is not None
    ]

    request_count = len(requests)
    consensus_runtime = sum(
        float(request["duration_sec"])
        for request in requests
        if request.get("request_role") == "consensus"
    )
    return {
        "strategy": strategy_name,
        "total_runtime_sec": round(total_runtime_sec, 3),
        "request_count": request_count,
        "number_of_model_switches": len(transitions),
        "runtime_per_model_sec": {
            model: round(duration, 3)
            for model, duration in sorted(per_model_runtime.items())
        },
        "consensus_runtime_sec": round(consensus_runtime, 3),
        "average_request_duration_sec": (
            round(sum(float(request["duration_sec"]) for request in requests) / request_count, 3)
            if request_count else None
        ),
        "total_model_load_time_sec": total_load_time,
        "total_model_unload_time_sec": None,
        "model_unload_time_note": (
            "Ollama chat responses expose load_duration, but not explicit unload_duration."
        ),
        "total_generation_time_sec": total_generation_time,
        "total_prompt_eval_time_sec": total_prompt_eval_time,
        "total_model_switch_overhead_sec": switch_overhead,
        "switch_overhead_method": switch_overhead_method,
        "percent_runtime_spent_switching": (
            round(switch_overhead / total_runtime_sec * 100.0, 1)
            if total_runtime_sec > 0 and switch_overhead is not None else None
        ),
        "peak_process_rss_bytes": max(process_peaks) if process_peaks else None,
        "peak_system_used_bytes": max(system_peaks) if system_peaks else None,
    }


def compute_improvement(depth_summary: dict[str, Any], breadth_summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "runtime_reduction_percent": percent_reduction(
            depth_summary.get("total_runtime_sec"),
            breadth_summary.get("total_runtime_sec"),
        ),
        "model_switch_reduction_percent": percent_reduction(
            depth_summary.get("number_of_model_switches"),
            breadth_summary.get("number_of_model_switches"),
        ),
        "model_switch_overhead_reduction_percent": percent_reduction(
            depth_summary.get("total_model_switch_overhead_sec"),
            breadth_summary.get("total_model_switch_overhead_sec"),
        ),
    }


def get_annotation_models() -> tuple[list[str], str, str]:
    from autoannotation.models import MODEL_AGGREGATION, MODEL_CONSENSUS, MODEL_SUMMARY

    return list(MODEL_SUMMARY), MODEL_CONSENSUS, MODEL_AGGREGATION


class MemorySampler:
    def __init__(self) -> None:
        try:
            import psutil  # type: ignore
        except ImportError:
            self.psutil = None
            self.process = None
        else:
            self.psutil = psutil
            self.process = psutil.Process(os.getpid())

    def sample(self, label: str) -> dict[str, Any]:
        sample = {
            "timestamp": utc_now_iso(),
            "label": label,
            "process_rss_bytes": None,
            "system_used_bytes": None,
            "system_percent": None,
        }
        if self.psutil is None or self.process is None:
            return sample
        memory = self.psutil.virtual_memory()
        sample.update({
            "process_rss_bytes": self.process.memory_info().rss,
            "system_used_bytes": memory.used,
            "system_percent": memory.percent,
        })
        return sample


class BenchmarkLlmExecutor:
    def __init__(self, cache_dir: str) -> None:
        from autoannotation import llms

        self.llms = llms
        self.handler = llms.LlmHandler(cache_dir)
        self.handler._read_cache = lambda model, prompt, json_schema: (None, None)
        self.handler._write_cache = lambda model, prompt, json_schema, response_text, duration_sec: True
        self.memory_sampler = MemorySampler()
        self.previous_model: str | None = None
        self.transitions: list[dict[str, Any]] = []
        self.requests: list[dict[str, Any]] = []
        self.memory_samples: list[dict[str, Any]] = []

    def safe_ollama_ps(self) -> Any:
        ps_function = getattr(self.llms.ollama, "ps", None)
        if ps_function is None:
            return None
        try:
            return make_jsonable(ps_function())
        except Exception as exc:
            return {"error": str(exc)}

    @contextlib.contextmanager
    def capture_ollama_response(self):
        original_chat = self.llms.ollama.chat
        captured: dict[str, Any] = {"response": None}

        def wrapped_chat(*args, **kwargs):
            response = original_chat(*args, **kwargs)
            captured["response"] = response
            return response

        self.llms.ollama.chat = wrapped_chat
        try:
            yield captured
        finally:
            self.llms.ollama.chat = original_chat

    def run_request(
        self,
        *,
        strategy_name: str,
        section: dict[str, Any],
        request_role: str,
        model_name: str,
        call: Callable[[], tuple[str, float]],
    ) -> str:
        model_switched = self.previous_model is not None and self.previous_model != model_name
        if model_switched:
            self.transitions.append({
                "previous_model": self.previous_model,
                "new_model": model_name,
                "timestamp": utc_now_iso(),
            })

        memory_before = self.memory_sampler.sample(
            f"{strategy_name}:{section['section_id']}:{model_name}:before"
        )
        self.memory_samples.append(memory_before)
        ollama_ps_before = self.safe_ollama_ps()
        start_timestamp = utc_now_iso()
        start_perf = time.perf_counter()

        with self.capture_ollama_response() as captured:
            response_text, ollama_reported_duration_sec = call()

        end_perf = time.perf_counter()
        end_timestamp = utc_now_iso()
        ollama_ps_after = self.safe_ollama_ps()
        memory_after = self.memory_sampler.sample(
            f"{strategy_name}:{section['section_id']}:{model_name}:after"
        )
        self.memory_samples.append(memory_after)

        self.requests.append({
            "strategy": strategy_name,
            "section_id": section["section_id"],
            "pmc_id": section["pmc_id"],
            "pmid": section.get("pmid"),
            "section_type": section["section_type"],
            "request_role": request_role,
            "model_name": model_name,
            "model_switched": model_switched,
            "switch_from_model": self.previous_model if model_switched else None,
            "start_timestamp": start_timestamp,
            "end_timestamp": end_timestamp,
            "duration_sec": round(end_perf - start_perf, 3),
            "ollama_reported_duration_sec": round_or_none(ollama_reported_duration_sec),
            "ollama_metrics": {
                key: round_or_none(value) if key.endswith("_sec") else value
                for key, value in ollama_metrics_from_response(captured["response"]).items()
            },
            "memory_before": memory_before,
            "memory_after": memory_after,
            "ollama_ps_before": ollama_ps_before,
            "ollama_ps_after": ollama_ps_after,
            "response_text": response_text,
        })
        self.previous_model = model_name
        return response_text


def resolve_context_from_args(args: argparse.Namespace):
    from autoannotation import organisms

    profile = args.profile
    if profile is None and args.organism is None:
        profile = "mtb-h37rv"
    return organisms.resolve_gene_context(
        profile_identifier=profile,
        organism_identifier=args.organism,
        strain_identifier=args.strain,
        locus=args.locus,
        name=args.name,
        gene_name_cache_dir=args.gene_name_cache,
        allow_online_name_lookup=not args.no_online_name_lookup,
        refresh_gene_name_cache=args.refresh_gene_name_cache,
        cache_supplied_name=args.cache_supplied_name,
    )


def collect_representative_sections(
    context,
    *,
    cache_dir: str,
    min_sections: int,
    max_sections: int,
) -> tuple[list[dict[str, Any]], list[Any], Any]:
    from autoannotation import pmc

    paper_manager = pmc.PmcPaperManager(cache_dir, organism_profile=context.profile)
    ranked_records = paper_manager.get_ranked_papers(context.locus, context.gene_name)
    selection = paper_manager.select_relevance_records(
        ranked_records,
        target_relevance=pmc.DEFAULT_TARGET_RELEVANCE,
        min_score=pmc.DEFAULT_MIN_SCORE,
        max_rank=pmc.DEFAULT_MAX_RANK,
        min_papers=pmc.DEFAULT_MIN_PAPERS,
        max_papers=pmc.DEFAULT_MAX_PAPERS,
    )

    sections: list[dict[str, Any]] = []
    for record in selection.selected_records:
        if len(sections) >= max_sections:
            break
        paper_sections: list[tuple[str, str]] = []
        abstract = paper_manager.get_abstract(record.pmc_id)
        if abstract is not None:
            paper_sections.append(("abstract", abstract))
        results = paper_manager.get_results(record.pmc_id)
        if results is not None:
            paper_sections.append(("results", results))
        discussion = paper_manager.get_discussion(record.pmc_id)
        if discussion is not None and discussion != results:
            paper_sections.append(("discussion", discussion))

        for section_type, text in paper_sections:
            if len(sections) >= max_sections:
                break
            sections.append({
                "section_id": f"PMC{record.pmc_id}:{section_type}:{len(sections) + 1}",
                "pmc_id": record.pmc_id,
                "pmid": record.pmid,
                "section_type": section_type,
                "relevance_score": record.score,
                "text": text,
            })

    if len(sections) < min_sections:
        print(
            f"Warning: collected only {len(sections)} sections, below requested minimum "
            f"{min_sections}. The benchmark will still run with the available sample."
        )
    return sections, ranked_records, selection


def run_depth_first(
    *,
    sections: list[dict[str, Any]],
    context,
    cache_dir: str,
) -> dict[str, Any]:
    model_summary, model_consensus, _ = get_annotation_models()
    executor = BenchmarkLlmExecutor(cache_dir)
    section_outputs: dict[str, dict[str, str]] = {}
    consensus_outputs: dict[str, str] = {}
    start = time.perf_counter()

    for section in sections:
        section_outputs[section["section_id"]] = {}
        candidates = []
        for model_name in model_summary:
            response = executor.run_request(
                strategy_name="depth_first",
                section=section,
                request_role="summary",
                model_name=model_name,
                call=lambda model_name=model_name, section=section: (
                    executor.handler.get_llm_gene_info_json(
                        context.locus,
                        context.gene_name,
                        section["text"],
                        model_name,
                        section_type=section["section_type"],
                        organism_profile=context.profile,
                    )
                ),
            )
            section_outputs[section["section_id"]][model_name] = response
            candidates.append(response)

        consensus = executor.run_request(
            strategy_name="depth_first",
            section=section,
            request_role="consensus",
            model_name=model_consensus,
            call=lambda candidates=candidates, section=section: (
                executor.handler.get_llm_consensus_json(
                    candidates,
                    excerpt=section["text"],
                    expected_gene_id=context.locus,
                    expected_name=context.gene_name,
                    model=model_consensus,
                    section_type=section["section_type"],
                    organism_profile=context.profile,
                )
            ),
        )
        consensus_outputs[section["section_id"]] = consensus

    total_runtime = time.perf_counter() - start
    summary = summarize_strategy(
        "depth_first",
        total_runtime,
        executor.requests,
        executor.transitions,
        executor.memory_samples,
    )
    return {
        "summary": summary,
        "requests": executor.requests,
        "model_transitions": executor.transitions,
        "memory_samples": executor.memory_samples,
        "section_summary_outputs": section_outputs,
        "consensus_outputs": consensus_outputs,
    }


def run_breadth_first(
    *,
    sections: list[dict[str, Any]],
    context,
    cache_dir: str,
) -> dict[str, Any]:
    model_summary, model_consensus, _ = get_annotation_models()
    executor = BenchmarkLlmExecutor(cache_dir)
    section_outputs: dict[str, dict[str, str]] = {
        section["section_id"]: {} for section in sections
    }
    consensus_outputs: dict[str, str] = {}
    start = time.perf_counter()

    for model_name in model_summary:
        for section in sections:
            response = executor.run_request(
                strategy_name="breadth_first",
                section=section,
                request_role="summary",
                model_name=model_name,
                call=lambda model_name=model_name, section=section: (
                    executor.handler.get_llm_gene_info_json(
                        context.locus,
                        context.gene_name,
                        section["text"],
                        model_name,
                        section_type=section["section_type"],
                        organism_profile=context.profile,
                    )
                ),
            )
            section_outputs[section["section_id"]][model_name] = response

    for section in sections:
        candidates = [section_outputs[section["section_id"]][model] for model in model_summary]
        consensus = executor.run_request(
            strategy_name="breadth_first",
            section=section,
            request_role="consensus",
            model_name=model_consensus,
            call=lambda candidates=candidates, section=section: (
                executor.handler.get_llm_consensus_json(
                    candidates,
                    excerpt=section["text"],
                    expected_gene_id=context.locus,
                    expected_name=context.gene_name,
                    model=model_consensus,
                    section_type=section["section_type"],
                    organism_profile=context.profile,
                )
            ),
        )
        consensus_outputs[section["section_id"]] = consensus

    total_runtime = time.perf_counter() - start
    summary = summarize_strategy(
        "breadth_first",
        total_runtime,
        executor.requests,
        executor.transitions,
        executor.memory_samples,
    )
    return {
        "summary": summary,
        "requests": executor.requests,
        "model_transitions": executor.transitions,
        "memory_samples": executor.memory_samples,
        "section_summary_outputs": section_outputs,
        "consensus_outputs": consensus_outputs,
    }


def default_output_path(output_dir: str) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path(output_dir) / f"ollama_model_switching_{timestamp}.json"


def fmt_seconds(value: float | int | None) -> str:
    if value is None:
        return "unavailable"
    return f"{float(value):.1f}s"


def fmt_percent(value: float | int | None) -> str:
    if value is None:
        return "unavailable"
    return f"{float(value):.1f}%"


def print_strategy_summary(title: str, summary: dict[str, Any]) -> None:
    print(f"\n{title}")
    print(f"* Total runtime: {fmt_seconds(summary['total_runtime_sec'])}")
    print(f"* Number of model switches: {summary['number_of_model_switches']}")
    print(f"* Total generation time: {fmt_seconds(summary['total_generation_time_sec'])}")
    print(f"* Total prompt eval time: {fmt_seconds(summary['total_prompt_eval_time_sec'])}")
    print(f"* Total load/unload overhead: {fmt_seconds(summary['total_model_switch_overhead_sec'])}")
    print(f"* Percent of runtime spent switching: {fmt_percent(summary['percent_runtime_spent_switching'])}")
    print(f"* Consensus runtime: {fmt_seconds(summary['consensus_runtime_sec'])}")
    print(f"* Average request duration: {fmt_seconds(summary['average_request_duration_sec'])}")
    print(f"* Peak process RSS: {summary['peak_process_rss_bytes'] or 'unavailable'} bytes")
    print(f"* Peak system memory used: {summary['peak_system_used_bytes'] or 'unavailable'} bytes")
    print(f"* Switch overhead method: {summary['switch_overhead_method']}")


def print_human_summary(results: dict[str, Any]) -> None:
    depth_summary = results["strategies"]["depth_first"]["summary"]
    breadth_summary = results["strategies"]["breadth_first"]["summary"]
    improvement = results["improvement"]

    print_strategy_summary("Depth-First Results", depth_summary)
    print_strategy_summary("Breadth-First Results", breadth_summary)

    print("\nImprovement")
    print(f"* Runtime reduction: {fmt_percent(improvement['runtime_reduction_percent'])}")
    print(f"* Reduction in model switches: {fmt_percent(improvement['model_switch_reduction_percent'])}")
    print(
        "* Reduction in load/unload overhead: "
        f"{fmt_percent(improvement['model_switch_overhead_reduction_percent'])}"
    )

    depth_switching = depth_summary.get("percent_runtime_spent_switching")
    breadth_switching = breadth_summary.get("percent_runtime_spent_switching")
    print("\nAnalysis")
    if depth_switching is not None and breadth_switching is not None:
        if depth_switching >= 20 and improvement.get("model_switch_overhead_reduction_percent", 0) > 0:
            print(
                "Model switching appears to be a significant bottleneck: depth-first spent "
                f"{depth_switching:.1f}% of wall time in measured or estimated switching overhead, "
                f"versus {breadth_switching:.1f}% for breadth-first."
            )
        else:
            print(
                "The measured switching share is modest relative to total wall time. Generation "
                "and prompt evaluation may be larger bottlenecks than model residency changes."
            )
    else:
        print(
            "Ollama did not expose enough timing data for a direct switching conclusion. "
            "Review per-request durations and model transition records in the JSON output."
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark depth-first versus breadth-first Ollama calls for gene annotation "
            "section inference. This is a manual, real-model benchmark."
        )
    )
    parser.add_argument("--profile", help="Configured organism profile, e.g. mtb-h37rv")
    parser.add_argument("--organism", help="Organism/species name or synonym")
    parser.add_argument("--strain", help="Optional strain/isolate/reference name or synonym")
    parser.add_argument("--locus", default="Rv0001", help="Gene locus to benchmark")
    parser.add_argument("--name", help="Optional gene name/symbol")
    parser.add_argument("--cache-dir", default="./.cache", help="Paper cache directory")
    parser.add_argument(
        "--gene-name-cache",
        default=DEFAULT_GENE_NAME_CACHE_DIR,
        help="Directory for cached locus-to-gene-name records",
    )
    parser.add_argument(
        "--no-online-name-lookup",
        action="store_true",
        help="Disable NCBI/UniProt gene-name lookup before paper retrieval",
    )
    parser.add_argument(
        "--refresh-gene-name-cache",
        action="store_true",
        help="Ignore cached online gene-name records and refresh from online sources",
    )
    parser.add_argument(
        "--cache-supplied-name",
        action="store_true",
        help="Write --name into the gene-name cache as a manual curated record",
    )
    parser.add_argument("--min-sections", type=int, default=20)
    parser.add_argument("--max-sections", type=int, default=30)
    parser.add_argument(
        "--output-dir",
        default="tests/benchmark_results",
        help="Directory where benchmark JSON should be written",
    )
    parser.add_argument("--output", help="Exact benchmark JSON output path")
    args = parser.parse_args(argv)
    if args.profile and args.organism:
        parser.error("use either --profile or --organism, not both")
    if args.min_sections < 1 or args.max_sections < 1:
        parser.error("--min-sections and --max-sections must be positive")
    if args.min_sections > args.max_sections:
        parser.error("--min-sections cannot exceed --max-sections")
    return args


def main(argv: list[str] | None = None) -> dict[str, Any]:
    from autoannotation import metadata

    args = parse_args(argv)
    context = resolve_context_from_args(args)
    sections, ranked_records, selection = collect_representative_sections(
        context,
        cache_dir=args.cache_dir,
        min_sections=args.min_sections,
        max_sections=args.max_sections,
    )
    if not sections:
        raise RuntimeError("No sections were collected; cannot run benchmark")

    print(
        f"Running benchmark for {context.profile.canonical_name} {context.locus} "
        f"({context.gene_name}) with {len(sections)} sections."
    )
    print("LLM response cache is bypassed for benchmark requests; production cache is untouched.")

    depth_first = run_depth_first(
        sections=sections,
        context=context,
        cache_dir=args.cache_dir,
    )
    breadth_first = run_breadth_first(
        sections=sections,
        context=context,
        cache_dir=args.cache_dir,
    )
    improvement = compute_improvement(depth_first["summary"], breadth_first["summary"])
    model_summary, model_consensus, model_aggregation = get_annotation_models()

    results = {
        "created_at": utc_now_iso(),
        "benchmark_version": 1,
        "cache_policy": "llm_response_cache_bypassed_for_benchmark_handler_only",
        "models": {
            "summary": model_summary,
            "consensus": model_consensus,
            "aggregation": model_aggregation,
        },
        "input": {
            "profile": context.profile.profile_id,
            "canonical_name": context.profile.canonical_name,
            "species_name": context.profile.species_name,
            "strain": context.profile.strain,
            "locus": context.locus,
            "gene_name": context.gene_name,
            "gene_name_source": context.gene_name_source,
            "cache_dir": args.cache_dir,
            "min_sections": args.min_sections,
            "max_sections": args.max_sections,
        },
        "paper_selection": {
            "total_papers_retrieved": len(ranked_records),
            "eligible_papers": selection.eligible_count,
            "selected_papers": len(selection.selected_records),
            "selection_mode": selection.selection_mode,
            "cumulative_relevance": round(selection.cumulative_relevance, 3),
            "excluded_warnings": sorted(metadata.DEFAULT_EXCLUDED_WARNINGS),
        },
        "sections": [
            {key: value for key, value in section.items() if key != "text"}
            for section in sections
        ],
        "strategies": {
            "depth_first": depth_first,
            "breadth_first": breadth_first,
        },
        "improvement": improvement,
        "notes": [
            "Depth-first and breadth-first use the exact same collected section texts.",
            "Prompts, schemas, models, and Ollama options are the production LlmHandler defaults.",
            "Ollama exposes load_duration on chat responses; explicit unload_duration is not exposed.",
            "If load_duration is unavailable, switch overhead is estimated as switched-request duration above the median same-model baseline.",
        ],
    }

    output_path = Path(args.output) if args.output else default_output_path(args.output_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf8") as output_file:
        json.dump(make_jsonable(results), output_file, indent=2)

    print_human_summary(results)
    print(f"\nSaved benchmark JSON: {output_path}")
    return results


if __name__ == "__main__":
    main()
