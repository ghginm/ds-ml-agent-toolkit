# Codex DS/ML toolkit pointer

Merge this fragment into the target repository's existing `AGENTS.md`; do not
replace that file. Codex discovers portable skills from `.agents/skills/`.

- Use `.agent-system/CONTROL.md` for operation and `.agent-system/SYSTEM.md`
  for the shared routing contract.
- Apply organization and repository instructions before workflow or skill guidance.
- Keep ordinary requests ordinary; load a contract from `.agent-system/workflows/`
  only for its explicit trigger.
- Project-specific skills remain allowed.
- Verify discovery with one safe read-only synthetic request.

Official references: [Codex agent skills](https://developers.openai.com/codex/skills)
and [`AGENTS.md` discovery](https://developers.openai.com/codex/guides/agents-md).
