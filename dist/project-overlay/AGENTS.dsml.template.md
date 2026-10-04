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

Before substantial work that depends on repository contents, run a best-effort
freshness check with `.agent-system/tooling/git_preflight.py --sync-mode fetch-check`,
or use `--sync-mode fast-forward-only` when repository policy permits updating a
clean behind branch. Skip Git for non-Git projects and continue locally when no
usable upstream exists.
Never stash, reset, merge, or rebase automatically. Warn concisely for dirty-behind,
diverged, or relevant fetch/authentication failures, but do not block unrelated
local work. Do not ask whether to use Git, fetch, or identify the current branch
when they can be detected. Reuse normal Git/SSH configuration; inspect remote
configuration and ssh-agent fingerprints only after authentication fails. Ask once
about identity selection only when multiple plausible identities remain and the
choice matters.

After a meaningful request, best-effort append only normalized metadata with
`.agent-system/tooling/record-request.py`. Do not ask the user, store the prompt,
or let auxiliary recording failure change the primary task outcome.

Use `.agent-system/project.yaml` only for stable facts that cannot be reliably
rediscovered. Technical availability never grants authorization. Preserve
project-owned instructions and keep harness-specific behavior in `adapters/`.
