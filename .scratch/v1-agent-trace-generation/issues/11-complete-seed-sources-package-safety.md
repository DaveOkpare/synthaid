# 11: Complete Seed sources and package safety

**What to build:** Let task authors consume all V1 Seed source forms safely while ensuring malformed records, unsafe package references, and non-portable identifiers fail before provider spend.

**Blocked by:** 10 — Run deterministic JSON and JSONL Seed collections

**Status:** ready-for-agent

**Type:** implementation

- [ ] CSV rows are loaded as flat mappings and Variable selectors address exact headers.
- [ ] A directory source enumerates matching files by normalized path and then record position.
- [ ] A Python iterable may provide Seeds without requiring an intermediate file.
- [ ] Optional JSON Schema validation runs before Variable extraction and instruction rendering.
- [ ] Nested dot paths are validated for JSON-compatible Seeds without pretending CSV values are nested.
- [ ] Package-relative paths cannot escape the Task Package, follow unsafe links, create resolution cycles, or collide after case normalization.
- [ ] Missing Agent instructions, missing step participation, undeclared components, unsafe names, and invalid references are precise validation failures.
- [ ] Record-level invalidity is indexed when origin is stable; source-enumeration failure fails the Run.
