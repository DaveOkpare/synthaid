# 11: Complete Seed sources and package safety

**What to build:** Let task authors consume all V1 Seed source forms safely while ensuring malformed records, unsafe package references, and non-portable identifiers fail before provider spend.

**Blocked by:** 10 — Run deterministic JSON and JSONL Seed collections

**Status:** resolved

**Type:** implementation

- [x] CSV rows are loaded as flat mappings and Variable selectors address exact headers.
- [x] A directory source enumerates matching files by normalized path and then record position.
- [x] A Python iterable may provide Seeds without requiring an intermediate file.
- [x] Optional JSON Schema validation runs before Variable extraction and instruction rendering.
- [x] Nested dot paths are validated for JSON-compatible Seeds without pretending CSV values are nested.
- [x] Package-relative paths cannot escape the Task Package, follow unsafe links, create resolution cycles, or collide after case normalization.
- [x] Missing Agent instructions, missing step participation, undeclared components, unsafe names, and invalid references are precise validation failures.
- [x] Record-level invalidity is indexed when origin is stable; source-enumeration failure fails the Run.

## Answer

CSV, directory, and Python iterable sources now share the existing compiler and
Runner lifecycle. CSV preserves exact flat headers and physical row origins;
directory sources require a glob and preflight matching files before yielding
work in normalized path/record order. The `seeds=` override accepts mappings and
explicit Seeds, retains stable origins, recomputes canonical digests, and isolates
invalid data from source iteration failures. Single-record compilation, collection
validation, convenience wrappers, CLI, persistence, and exports use the same path.

Optional `[seed] schema` files are validated with an offline registry before ID
Variable extraction or rendering, frozen into the prepared package, and included
in its digest and source snapshot. JSON selectors use validated nested dot paths;
CSV selectors address exact headers, including spaces and dots.

Shared portable-name and confined-path rules cover component identifiers,
case-normalized collisions, exact file spelling, traversal, symbolic links, and
cycles. Conventional Agent, Reviewer, step, and Verifier layouts report their
specific missing/undeclared paths. Both exporters check every selected source
before opening their destination and protect complete Run/Trace evidence and
standalone snapshot sidecars against direct, symbolic-link, and hard-link writes.
Run output roots reject symbolic links, with explicit support for the standard
macOS `/private` system aliases. This is static local path validation; broader
persistence fault recovery remains ticket 18.

Verification: 132 focused tests passed across Seed sources, package safety,
collections, steps, and CLI; mypy passed for source/tests/example; repository-wide
Ruff lint and formatting checks passed. The offline mixed CSV/JSON example
validated and generated three accepted Traces, including through `/tmp`, and its
iterable script generated two accepted Traces. The parent independently confirmed
all four import-safety checks. The full suite remains scheduled after ticket 19.

Review follow-up: widened the public iterable input annotation to accept ordinary
`JsonValue` mappings, including nested mutable JSON arrays, while preserving
immutable Seed/Plan output types. A typed `list[dict[str, JsonValue]]` regression
now compiles and runs through the public APIs, and proves caller mutation cannot
change compiled or persisted arrays. The regression failed mypy before the fix;
all 15 Seed-source tests, source/tests/example mypy, and focused Ruff lint/format
checks passed afterward.

Persisted-origin regression follow-up: searched all test origin expectations and
updated the existing Runner snapshot assertion to include the additive
`format = "json"` field. All 19 Runner and Seed-source tests passed, alongside
targeted source/test mypy and Ruff lint/format checks. No runtime change was needed.

See [collection/source usage](../../../README.md#run-a-seed-collection), the
[mixed-source package](../../../examples/seed-sources/task.toml), and the
[iterable example](../../../examples/seed-sources/run.py).
