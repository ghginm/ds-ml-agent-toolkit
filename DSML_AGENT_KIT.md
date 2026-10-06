# DS/ML Agent Kit

## Quick setup

1. Copy this overlay into your project without overwriting project-owned files.
2. Open the project with Hermes.
3. Ask: **“Set up the DS/ML Agent Kit for this project.”**

The agent will inspect the project, integrate its instructions, validate the kit, and report whether it is ready.

## Common usage

For ready-to-use prompts, report controls, and research options, see
[`.agent-system/CONTROL.md`](.agent-system/CONTROL.md). This card does not
duplicate them.

## Git

Existing Git repositories are reused. The agent may initialize Git when appropriate, or skip Git for disposable projects where version control adds no value.

## Advanced / internals

Most users do not need to edit files inside `.agent-system`. It holds the
control reference, system behavior notes, adapters, templates, validation
tooling, and workflow contracts.