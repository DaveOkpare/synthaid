# Domain Docs

This is a single-context repository.

## Before exploring

- Read `CONTEXT.md` at the repository root when it exists.
- Read ADRs under `docs/adr/` that affect the area being changed.
- If these files do not exist, proceed without requesting that they be created.

## Use the glossary vocabulary

Use domain terms as defined in `CONTEXT.md` in issues, specifications, tests, APIs, and implementation discussions. Avoid synonyms that the glossary explicitly rejects.

If a required concept is missing, reconsider whether new vocabulary is necessary or record the gap for domain-modeling work.

## Respect architectural decisions

Surface any conflict with an existing ADR explicitly rather than silently overriding it.

## Layout

- `CONTEXT.md` contains the domain glossary.
- `docs/adr/` contains system-wide architectural decisions.
- `docs/specs/` contains development specifications.
- `src/agentinstruct/` contains the implementation.
