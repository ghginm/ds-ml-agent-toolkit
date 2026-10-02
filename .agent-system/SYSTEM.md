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
signals. Autoresearch additionally uses `evaluation.yaml`, a content-addressed
experiment journal, and a project-local cross-run exposure ledger; transactional
finalization separates research decisions from evidence, independent validation,
branch, and production-integration state. The toolkit core is project-agnostic:
runtime validation treats metric names as opaque identifiers, and scientific
semantics such as direction, guardrail limits, and evaluation strategy enter only
through the explicit reconstructed contract. See
[`docs/LEARNING_LOOP.md`](docs/LEARNING_LOOP.md) for the detailed
maintenance lifecycle.

For autoresearch, keep three roots explicit: `canonical_project_root` is the user's
initiating repository/worktree and owns durable evidence;
`experiment_worktree_root` is disposable isolation for candidate source changes,
commits, evaluation, and rollback; `toolkit_root` supplies toolkit templates and
version information. Autoresearch may execute in an isolated worktree, but durable
run evidence belongs to the canonical user project root from which the run was
initiated. Never use the isolated worktree or toolkit installation as the sole
evidence location. Relative `.agent-system/runs/...` references are relative to the
canonical project root, not the process current directory.

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
