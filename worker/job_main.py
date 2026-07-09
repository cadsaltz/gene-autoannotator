import argparse
import json
import sys

from shared.job_contract import AnnotationJobRequest
from worker.executor import _run_inprocess


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run one annotation job in an isolated subprocess.")
    parser.add_argument("--request-file", required=True, help="Path to JSON AnnotationJobRequest payload.")
    args = parser.parse_args(argv)

    with open(args.request_file, encoding="utf-8") as request_file:
        request = AnnotationJobRequest(**json.load(request_file))

    result = _run_inprocess(request)
    json.dump(result, sys.stdout)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
