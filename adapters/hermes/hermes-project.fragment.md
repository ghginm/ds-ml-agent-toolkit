# Hermes DS/ML toolkit pointer

Merge the distributed `AGENTS.dsml.template.md` into shared `AGENTS.md` when
possible. Use `.hermes.md` only for intentional Hermes-specific context because
it may shadow shared instructions.

Hermes discovers `.agents/skills/` after an operator runs `hermes skills trust`
inside the repository and starts a new session. Trust enables discovery; it does
not authorize data access, compute, network use, or mutation.

- Use `.agent-system/CONTROL.md` for operation and `.agent-system/SYSTEM.md`
  for the shared routing contract.
- Keep ordinary requests ordinary; load a contract from `.agent-system/workflows/`
  only for its explicit trigger.
- Project-specific skills remain allowed.
- Verify discovery with a safe read-only synthetic request.

Official references: [Hermes context files](https://hermes-agent.nousresearch.com/docs/user-guide/features/context-files)
and [project-local skills](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills#project-local-skills).
