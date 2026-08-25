import argparse

from dispatcher.loop import dispatch_once


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Submit Slurm workers for queued annotation jobs"
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=("once",),
        default="once",
        help="Peek and submit once (default: once)",
    )
    parser.parse_args()

    launched = dispatch_once()
    print(f"Submitted {launched} worker job(s).", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
