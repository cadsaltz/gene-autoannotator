# Experiments

Paper and benchmark experiments for Gene Autoannotator.

- **`paper/`** — claim-driven studies for the research paper (protocol, frozen configs, fixtures, runners, results, analysis).
- Production unit/API tests stay under `tests/`. Throughput bench protocol stays under `docs/worker-bench-protocol.md`.

Do not treat these runners as CI unit tests. They are empirical protocols with frozen inputs and auditable artifacts.
