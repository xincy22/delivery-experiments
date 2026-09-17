# Working agreement

This is a small algorithm experiment, not an optimization framework.

- Keep one independent C++ solver. Do not call external LP/MIP, matching, SAT or optimization packages.
- Preserve the original TSV rows and IDs. Data loading is not candidate pruning.
- Keep strategy, indexes and prices inside the solver. Do not add registries, adapters or solver-to-solver dependencies.
- Prefer a few cohesive functions over forwarding wrappers. Small duplication is acceptable.
- The native executable must never read reference objectives, historical solutions or third-party solver artifacts.
- Benchmark and verification are standard-library Python. References belong to evaluation only.
- Every reported performance claim must identify the source version, parameters, seeds and timing scope.
- Never call a budget-limited neighborhood repair proven optimal unless its tree was exhausted.
- Validate outputs against original rows and validate lower bounds against ALL original candidates.
- Do not commit local tools, binaries, caches, credentials or full Git LFS data objects as ordinary Git blobs.
- Keep the derivations in docs/algorithm.md consistent with the implementation.
