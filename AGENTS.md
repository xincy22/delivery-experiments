# Project Working Agreement

This repository is an algorithm experiment project, not a reusable framework.

## Core Principles

- Prefer short, direct code over abstract, extensible code.
- Do not add compatibility layers, migration shims, adapter layers, registries, or plugin-style interfaces unless explicitly requested.
- Do not design for future solver replacement.
- Accept small amounts of duplication if that keeps code flatter and easier to read.
- Keep the number of files and jumps low.

## Data Layer

- The data loading step should preserve the raw input view as much as possible.
- A loaded dataset should still look obviously like the original file contents.
- Only do necessary preprocessing during load:
  - parse types
  - normalize obvious row shape issues such as sorted order tuples
  - collect minimal global sets like all orders or all riders
- Do not put solver-specific derived fields into the load step.
- Do not mix loading with greedy scoring, scarcity features, search indices, or local-search acceleration structures.
- Names in the data layer should follow the raw data, not the optimization model.
- If something is fundamentally a row from the file, prefer names like `row` or `rows` over names like `assignment`, `decision`, or `solution`.

## Solver Organization

- Solvers should be as independent as possible.
- One solver should not import or call another solver.
- A solver may reuse the same idea as another solver, but it should implement its own logic locally.
- If a solver needs an initial feasible solution, implement that initialization inside that solver rather than depending on another solver.
- Shared code is allowed only for low-level solver-agnostic operators.
- If a helper contains solver strategy, keep it inside that solver.
- Do not make one solver depend on another solver just because the dependency feels convenient.
- Solver-specific needs should be managed inside that solver.
- If a future solver needs something unusual, add it locally to that solver first rather than promoting it to a project-wide pattern.

## Layer Boundaries

- Upper layers should provide only the most basic, most general context.
- Do not let upper layers pre-design control surfaces for lower layers.
- Benchmark should know about cases, time limits, and results. It should not assume solver internals.
- Do not promote a parameter into a shared interface just because one solver happens to need it.
- If a need is not already clearly common across multiple solvers, keep it local.
- Common code should grow out of real repeated use, not anticipated reuse.
- Return results upward, but keep process details local.
- Do not promote solver-internal process information into shared result structures.
- If something is only useful for observing or debugging a solver's internal behavior, keep it inside that solver and print it as local log output if needed.
- Do not add fields to shared result types just because they might be useful later.
- Shared result types should contain only stable cross-solver outputs such as feasibility, total cost, runtime, and the final selected rows.

## Abstraction Threshold

- Do not add a helper, wrapper, or intermediate type unless it clearly removes real complexity.
- Avoid thin wrappers such as config-merging layers, `solve_prepared`, resolver helpers, or one-step conversion layers.
- Avoid creating types whose only purpose is to carry data from one nearby function to another.
- Prefer passing simple values or raw structures over introducing new orchestration objects.
- If a piece of logic is used in only one solver, keep it in that solver even if it is a little long.

## Function Design

- Prefer functions with a single clear semantic responsibility.
- A function may be moderately complex if all of its logic serves one coherent purpose.
- Do not split cohesive logic into thin wrapper functions.
- If a helper only forwards, renames, lightly repackages, or partially delegates another call, it usually should not exist.
- If the purpose of a function is hard to describe in one sentence, its boundary is probably unclear.
- Prefer semantic boundaries over line-count-based splitting.
- A good function in this repo is allowed to be substantial, but it should still do one complete thing.

## Naming

- Names should follow the most concrete view available.
- Use raw-data names first, algorithm names second.
- Only use names like `solution`, `selected_rows`, or `total_cost` when the code is actually operating at the solving stage.
- Avoid “upgrading” simple concepts into more grandiose names.

## Collaboration Rules For Codex

- Before making large edits, first align on structure if the change introduces new modules, new abstractions, or cross-solver shared code.
- When multiple designs are possible, prefer the one with fewer layers.
- When unsure between abstraction and duplication, default to duplication unless the abstraction is clearly simpler.
- Do not preserve old APIs unless the user explicitly asks for compatibility.
- If the current code violates these rules, prefer simplifying it instead of extending the existing pattern.
- Do not introduce framework-style extensibility in the name of future growth.
- Project extensibility should come from local independence, not from global pre-abstraction.
