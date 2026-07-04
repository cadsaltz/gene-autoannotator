import argparse
import sys

from worker import agent, bootstrap
from worker.lock import acquire_worker_lock


def main():
    parser = argparse.ArgumentParser(description="Gene Autoannotator worker agent")
    parser.add_argument("--coordinator-url", dest="coordinator_url")
    parser.add_argument("--token", dest="token")
    parser.add_argument("--memory-gb", dest="memory_gb", type=float)
    args = parser.parse_args()
    overrides = {}
    if args.coordinator_url:
        overrides["COORDINATOR_URL"] = args.coordinator_url
    if args.token:
        overrides["WORKER_API_TOKEN"] = args.token
    if args.memory_gb is not None:
        overrides["ANNOTATION_MEMORY_BUDGET_GB"] = args.memory_gb
    print("Starting gene-autoannotator worker...", flush=True)
    bootstrap.ensure_worker_env(cli_overrides=overrides)
    acquire_worker_lock()
    try:
        agent.run()
    except KeyboardInterrupt:
        print("Worker stopped.", flush=True)
        sys.exit(0)


if __name__ == "__main__":
    main()
