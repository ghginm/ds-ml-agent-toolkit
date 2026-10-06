<!-- DS/ML Agent Kit:BEGIN managed -->
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

## Structural Change Discipline

Apply this only when a request materially changes project layout, multiple top-level
directories, package/module structure, major entry points, build/package setup,
scripts-to-package migration, or another broad architectural reorganization. A
normal feature, fix, or small experiment remains an ordinary edit and must not create
a worktree or staging directory merely because isolation exists.

Before high-blast-radius mutation, inspect the current structure and determine the
intended end-state. Identify canonical new paths, legacy paths that would become
obsolete, compatibility requirements, migration risk, and likely duplicate concepts.
For Git projects, prefer a dedicated `refactor/...` branch in a sibling Git worktree
when practical; do not make a disconnected copy. For non-Git projects, use a sibling
staging/rework directory only when isolation adds real value.

A refactor worktree is temporary execution and review isolation, not a second permanent project.
After validation, name the branch that contains the completed
refactor. When integration into the canonical branch is authorized and safe,
integrate through normal Git history, verify the canonical working tree, and remove
the temporary worktree when it is no longer needed. When integration is not
authorized, leave the branch and worktree intact and state exactly where the
completed result lives; never silently merge or delete it, and never finish with
two directories that both appear canonical without explaining their state.

Treat migration cleanliness as completion work. Verify behavioral parity at a level
appropriate to the project before replacing or removing old code. Each legacy
component must be migrated and removed, deliberately retained as canonical, retained
as an explicit compatibility shim, or intentionally deprecated and documented.
Do not accept accidental old/new coexistence, duplicate concepts, abandoned entry
points, unnecessary root clutter, or agent-generated caches as a completed migration.
Keep the canonical execution path and user commands clear. Infer a conventional
end-state without asking unless a genuinely consequential structural choice remains.
For structural-refactor completion, report the canonical structure, what migrated,
which legacy paths were removed or retained and why, and the validation performed.

After a meaningful structural or multi-file change, perform a lightweight
repository-level completion pass. Check for duplicate concepts or equivalent old/new
directories, obsolete root implementations, duplicated configuration, and multiple
apparent entry points; resolve them or document an intentional compatibility shim.
Check the intended Git changes for `__pycache__`, inappropriate `.pytest_cache`,
temporary outputs, scratch/debug data, and accidental agent artifacts. Remove them,
and update `.gitignore` when the work introduces a repeatable generated or cache
artifact that should stay untracked. Confirm every newly added root-level file belongs
there and that a human can still find how to run the main workflow, tests, and primary
project task. Do not force README or other documentation churn for a small edit.

Refresh `PROJECT_MAP.md` before structural work is complete when the change materially
alters architecture, major directories, important data flow, the model pipeline,
core entry points, or major dependencies/components. Do not update it for trivial edits.
Update `AGENTS.md` or equivalent project instructions only when durable project-level
guidance changed; never use project instructions as a change log.

When a commit is requested or otherwise authorized, default to Conventional Commits:
`feat(scope): ...`, `fix(scope): ...`, `refactor(scope): ...`, `test(scope): ...`,
`docs(scope): ...`, or `chore(scope): ...`; omit the scope when it adds no useful
information. Describe the actual logical change rather than repeating the prompt,
and prefer one logical change per commit without mechanically splitting tiny related
edits. Before a requested commit or push, inspect Git status and the relevant diff,
reuse `git_preflight.py` for upstream state, run proportionate validation, and ensure
incidental generated, cache, or temporary files are not accidentally included; retain
repository-required generated outputs when project instructions require them. Exclude
unrelated user changes; separate them when practical, otherwise do not commit until scope
is clear. Push only when push is authorized. The presence of Git alone never authorizes a
commit or push, and non-Git projects continue normally.

After a meaningful request, best-effort append only normalized metadata with
`.agent-system/tooling/record-request.py`. Do not ask the user, store the prompt,
or let auxiliary recording failure change the primary task outcome.

Use `.agent-system/project.yaml` only for stable facts that cannot be reliably
rediscovered. Technical availability never grants authorization. Preserve
project-owned instructions and keep harness-specific behavior in
`.agent-system/adapters/`.

<!-- DS/ML Agent Kit:END managed -->
