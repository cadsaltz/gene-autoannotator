"""Backward-compatible entry point; delegates to run_bias_1_vs_3."""

from experiments.paper.runners.run_bias_1_vs_3 import main, run_bias_experiment

run_bias_general_experiment = run_bias_experiment

if __name__ == '__main__':
    main()
