import argparse
import sys

from worker import executor


def _add_serve_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--coordinator-url", dest="coordinator_url")
    parser.add_argument("--token", dest="token")
    parser.add_argument("--memory-gb", dest="memory_gb", type=float)


def main():
    parser = argparse.ArgumentParser(description="Gene Autoannotator worker agent")
    _add_serve_args(parser)
    sub = parser.add_subparsers(dest="command")

    serve_parser = sub.add_parser("serve", help="Run worker in coordinator serve mode")
    _add_serve_args(serve_parser)

    bench_parser = sub.add_parser("bench", help="Run a local batch benchmark")
    bench_parser.add_argument("--jobs", required=True, help="JSONL file with AnnotationJobRequest per line")
    bench_parser.add_argument("--slots", type=int, default=None, help="Override concurrent worker slots")
    bench_parser.add_argument("--cache", choices=["cold", "warm"], default="cold")
    bench_parser.add_argument("--report", default=None, help="Report path (default: reports/<timestamp>.json)")
    bench_parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory for annotation JSON outputs (local disk only)",
    )
    bench_parser.add_argument(
        "--keep-alive",
        default="-1",
        help="Ollama keep_alive for all LLM calls (default -1 = never unload)",
    )
    bench_parser.add_argument(
        "--no-warm-models",
        action="store_true",
        help="Skip pre-loading all required models before the batch",
    )
    bench_parser.add_argument(
        "--configure-fleet",
        action="store_true",
        help="Prompt for Ollama fleet settings (servers, parallel, slots)",
    )
    bench_parser.add_argument(
        "--no-dashboard",
        action="store_true",
        help="Disable the live in-place dashboard even on a TTY; use linear logs instead",
    )
    bench_parser.add_argument(
        "--log-file",
        default=None,
        help="Write verbose logs to this file (default: alongside --report when dashboard is active)",
    )

    args = parser.parse_args()
    command = args.command or "serve"
    if command == "serve":
        from worker.serve import main as serve_main

        try:
            serve_main(args)
        except KeyboardInterrupt:
            print("Worker stopped.", flush=True)
            sys.exit(0)
    elif command == "bench":
        from worker.bench import main as bench_main

        try:
            sys.exit(bench_main(args))
        except KeyboardInterrupt:
            print("Bench stopped.", flush=True)
            executor.terminate_active_jobs()
            sys.exit(130)


if __name__ == "__main__":
    main()
