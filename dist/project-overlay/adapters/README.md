# Harness adapters

The released overlay keeps one harness-neutral system: `.agent-system/CONTROL.md`,
`.agent-system/SYSTEM.md`, workflow contracts, and portable `.agents/skills/`.
Adapters only connect that system to native harness discovery.

| Harness | Native skill source | Merge target | Adapter |
| --- | --- | --- | --- |
| Codex | `.agents/skills/<name>/SKILL.md` | root or nested `AGENTS.md` | [Codex](codex/AGENTS.fragment.md) |
| Copilot | `.agents/skills/<name>/SKILL.md` | `.github/copilot-instructions.md` | [Copilot](copilot/copilot-instructions.fragment.md) |
| Hermes | trusted `.agents/skills/<name>/SKILL.md` | preferably shared `AGENTS.md` | [Hermes](hermes/hermes-project.fragment.md) |

Merge only the active harness fragment and preserve existing project instructions.
Adapters do not copy workflow details, grant permissions, configure services, or
require subagents. Verify discovery with a safe read-only prompt after activation.
