# DS/ML Agent Kit — System

## 5-minute architecture

```text
CONTROL.md
    |
    v
routing contract
    |
    +--> ordinary request --> normal agent reasoning
    |
    +--> explicit workflow
            |
            v
          skills
            |
            v
    project/runtime state
            |
            v
         outputs
```

| Component | Purpose | User normally edits it? |
| --- | --- | --- |
| `CONTROL.md` | Operate the toolkit | No |
| `project.yaml` | Stable facts not reliably rediscoverable | Rarely |
| `workflows/` | Explicit orchestration and completion contracts | No |
| `.agents/skills/` | Reusable implementation expertise | No |
| capability policy | Authorized recurring actions | Only deliberately |
| `runs/` | Evidence for tracked or controlled work | No |
| `local/request-*.{jsonl,yaml}` | Ignored request frequency/friction signals | No |

## Responsibility boundaries

| Layer | Owns | Does not own |
| --- | --- | --- |
| Repository/organization policy | Permissions, prohibitions, local invariants | DS/ML procedure |
| Routing contract | When normal work or a named workflow applies | Detailed analysis or execution |
| Workflow contract | Defaults, skill sequence, quality gates | Harness integration |
| Skill | How specialized work is performed | User-facing control syntax |
| Adapter | Native discovery and activation | Alternate workflow definitions |
| Project state | Stable local facts, approved policy, evidence | Copies of authoritative source config |

## Routing precedence

1. Organization, repository, and path policy wins.
2. An explicit named workflow beats inferred routing.
3. Explicit workflow parameters beat workflow defaults.
4. A technical report or PDF report uses
   [`workflows/technical-report.md`](workflows/technical-report.md).
5. Explicit autoresearch—or unmistakable autonomous repeated measurable
   optimization—uses [`workflows/autoresearch.md`](workflows/autoresearch.md).
6. `Independently validate...` uses
   [`workflows/independent-validation.md`](workflows/independent-validation.md).
7. Everything else remains normal agent work. Skills may still be used naturally;
   no workflow record or form is created merely because a contract exists.

## Project configuration

`project.yaml` is a small cache for durable facts that matter across tasks and
cannot be recovered cheaply from authoritative repository files. It must not copy
package manifests, CI, Makefiles, model configuration, orchestration manifests,
or obvious source paths. Optional unknowns stay absent or `null`. Technical
availability never grants authorization.

## Run evidence and learning

Tracked or controlled work may create sibling `run.yaml` and `learning.yaml`
records. Ordinary work does not require them. `run.yaml` holds execution evidence;
`learning.yaml` holds sparse routing/outcome metadata and at most a few actionable
signals. Meaningful ordinary requests may append compact sanitized metadata to
ignored `.agent-system/local/request-events.jsonl`; deterministic thresholded
review writes `request-patterns.yaml`. Neither file stores full prompts, terminal
output, secrets, raw project data, or hidden reasoning, and frequency alone never
changes toolkit content. Autoresearch additionally uses `evaluation.yaml`, a content-addressed
experiment journal, and a project-local cross-run exposure ledger; transactional
finalization separates research decisions from evidence, independent validation,
branch, and production-integration state. The toolkit core is project-agnostic:
runtime validation treats metric names as opaque identifiers, and scientific
semantics such as direction, guardrail limits, and evaluation strategy enter only
through the explicit reconstructed contract. See
[`docs/LEARNING_LOOP.md`](docs/LEARNING_LOOP.md) for the detailed
maintenance lifecycle.

Git is optional except for workflows such as autoresearch that explicitly require
isolated versioned mutation. Before substantial repository-dependent work, agents
use `git_preflight.py` for a best-effort freshness check while non-Git projects
continue normally. A clean behind branch may be fast-forwarded only when policy
permits; dirty or diverged worktrees are never stashed, reset, merged, or rebased
automatically. Authentication diagnostics reuse configured Git/SSH behavior and
inspect only remote configuration and public ssh-agent fingerprints after failure.

## Structural Change Discipline

Use this discipline for high-blast-radius changes to project layout, multiple
top-level directories, package/module boundaries, major entry points, build/package
setup, script-to-package migration, extensive reorganization, or a broad
architectural refactor. Do not trigger it for a normal feature, fix, bounded model
experiment, or routine file-level change.

Before mutation, inspect the current repository structure and define the intended
end-state. Record the canonical new paths, legacy paths that become obsolete,
compatibility requirements, migration risks, and likely duplicate concepts. In a Git
repository, prefer a dedicated `refactor/...` branch in a sibling Git worktree when
practical so the large change is isolated without a disconnected copy. For a non-Git
project, a sibling staging/rework directory is appropriate only when isolation has
clear value; ordinary edits must not create one.

A refactor worktree or staging directory is temporary execution and review isolation,
never a second permanent project. After validation, clearly identify
which branch contains the completed refactor. When integration into the canonical
branch is authorized and safe, integrate through normal Git history, verify the
canonical working tree, and remove the temporary worktree once it is no longer
needed. When integration is not authorized, leave the refactor branch and worktree
intact, tell the user exactly where the completed result lives, and never silently
merge or delete it. Never finish with two directories that both appear canonical
without explaining their state.

Migration cleanliness is an acceptance criterion, not optional polish. Before old
code is replaced or removed, verify behavioral parity to the level appropriate for
the project. Every legacy component ends as one of: migrated and removed;
deliberately retained as canonical; retained as an explicit compatibility shim; or
intentionally deprecated and documented. Accidental coexistence such as `test/` and
`tests/`, `training.py` and `training/`, or old/new config directories is incomplete.
The final root should follow ecosystem conventions, avoid abandoned scripts and
agent-generated caches, keep user commands simple, and expose one clear canonical
execution path. Infer the conventional end-state automatically; ask only when a
consequential ambiguity remains. The completion report names the canonical
structure, migrated components, removed or retained legacy paths, and validation.

The shared completion hygiene check is intentionally lightweight rather than a new
linting or governance system. After meaningful structural or multi-file work, perform
a repository-level pass: inspect the repository and intended Git changes for duplicate
concepts, equivalent legacy and new directories, obsolete root implementations,
duplicate configs, ambiguous entry points, generated caches, temporary or debug
output, scratch files, and accidental agent artifacts. Resolve accidental duplication;
preserve a compatibility shim only when its consumer and purpose are documented.
Review newly added root-level files and keep only those that genuinely belong at the
root. If the work creates a repeatable cache or generated artifact that should never
be tracked, add the narrow `.gitignore` rule.

Completion also checks that the main workflow, tests, and primary project task remain
reasonably discoverable from authoritative repository evidence. This does not require
README edits after every small change. Refresh `PROJECT_MAP.md` when architecture,
major directories, important data flow, the model pipeline, core entry points, or
major dependencies/components materially change; leave it untouched for trivial edits.
Change `AGENTS.md` or equivalent project instructions only for durable project-level
guidance, never as a change log of completed work.

When local commits are authorized, use Conventional Commits by default:
`feat(scope): ...`, `fix(scope): ...`, `refactor(scope): ...`, `test(scope): ...`,
`docs(scope): ...`, or `chore(scope): ...`; scope is optional when it adds no useful
information. The subject describes the actual logical change, not the request text.
Prefer one logical change per commit without splitting tiny related edits. Before a
requested commit or push, inspect status and the relevant diff, reuse
`git_preflight.py` for upstream state, run lightweight relevant validation, and keep
incidental generated, cache, or temporary files from being accidentally included;
retain repository-required generated outputs when project instructions require them.
Exclude unrelated user changes; separate them when practical, otherwise stop before
committing until scope is clear. Push only when the exact remote write is authorized.
Git availability alone never authorizes commits or pushes, and non-Git projects
continue normally.

For autoresearch, keep three roots explicit: `canonical_project_root` is the user's
initiating repository/worktree and owns durable evidence;
`experiment_worktree_root` is disposable isolation for candidate source changes,
commits, evaluation, and rollback; `toolkit_root` supplies toolkit templates and
version information. Autoresearch may execute in an isolated worktree, but durable
run evidence belongs to the canonical user project root from which the run was
initiated. Never use the isolated worktree or toolkit installation as the sole
evidence location. Relative `.agent-system/runs/...` references are relative to the
canonical project root, not the process current directory.

## Toolkit runtime states

Setup, repair, and upgrade share one runtime path in
`.agent-system/tooling/onboard-project.py`. A trusted distribution overlay is
classified against the installed `.agent-system/VERSION` and manifest: no
installed kit means a fresh install, an equal version means same-version
repair/recheck, a newer source means an upgrade, and an older source is never
silently applied — it requires explicit downgrade intent. Only manifest-owned
runtime files are written or removed. Project code, `PROJECT_MAP.md`,
`project.yaml`, local learning/log state, run evidence, project-specific
skills, and user-written instructions are project-owned and preserved. An
obsolete toolkit file is removed only when the installed copy still matches
the old manifest hash; a modified copy is preserved with a warning, and
similarly named unknown files are never touched. The managed toolkit block in
the project instruction target (delimited by `DS/ML Agent Kit` HTML comment
markers) is refreshed in place and never duplicated; pre-managed installs
migrate when the toolkit section can be located exactly, and are otherwise
preserved unchanged and reported for a manual merge. A sync validates the
complete plan before writing anything, applies per-file atomic writes, rewrites
the manifest last, and finishes with installed-project validation, so a failed
run reports `ACTION_REQUIRED` instead of a falsely clean success. Re-running an
upgrade with the same distribution is idempotent.

## Adapters and harness integration

The overlay ships thin Codex, Copilot, and Hermes adapters. They point the active
harness to this routing contract and `.agents/skills/`; they do not duplicate
skills, workflow details, permissions, or product bindings. Merge only the adapter
for the active harness and preserve existing repository instructions.

## Extension and release rules

| Need | Narrowest change |
| --- | --- |
| Project fact or command | Project instructions or authoritative project config |
| Reusable detail inside a workflow | Existing skill reference |
| New explicit orchestration sequence | Small Markdown workflow contract |
| Genuinely distinct recurring expertise | New skill, backed by evals |
| Permission for a recurring action | Reviewed capability policy |

Released skills and policy never change automatically from runtime learning.
Maintainers update source, add behavior-focused evals, rebuild the overlay, run
validation/tests, inspect the distribution, and require human review.
