## Agent system

Project-specific guidance is defined in this file.

- Operate from `.agent-system/CONTROL.md`; use `.agent-system/SYSTEM.md` for architecture and maintenance detail.

Routing precedence:

1. Apply organization, repository, and path policy first.
2. Honor an explicit workflow and its user-supplied parameters before defaults.
3. Route technical reports/PDF reports, autoresearch, and independent validation
   through the matching contract in `.agent-system/workflows/`.
4. Keep every other request as normal agent work. Skills may support that work
   naturally; do not require a workflow, form, configuration edit, or run record.

Use `.agent-system/project.yaml` only for stable facts that cannot be reliably
rediscovered. Technical availability never grants authorization. Preserve
project-owned instructions and keep harness-specific behavior in `adapters/`.
