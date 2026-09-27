# Issue tracker: Local Markdown

Issues and specs for this repo live as Markdown files in `.scratch/`.

## Conventions

- One feature per directory: `.scratch/<feature-slug>/`
- The spec is `.scratch/<feature-slug>/spec.md`
- Implementation issues are one file per ticket at `.scratch/<feature-slug>/issues/<NN>-<slug>.md`, numbered from `01`
- Triage state is recorded as a `Status:` line near the top of each issue file
- Comments and conversation history are appended under `## Comments`

## Publishing

When a skill says “publish to the issue tracker,” create the relevant feature directory and write its spec or issue beneath `.scratch/<feature-slug>/`.

## Fetching tickets

Read the referenced Markdown file. The user will normally provide its path or issue number.

## Wayfinding operations

- Map: `.scratch/<effort>/map.md`
- Child ticket: `.scratch/<effort>/issues/NN-<slug>.md`
- Each ticket records `Type:` and `Status:`
- Dependencies use `Blocked by: NN, NN`
- Claiming a ticket changes its status to `claimed`
- Resolving a ticket appends an `## Answer`, changes its status to `resolved`, and adds a context pointer to the map
