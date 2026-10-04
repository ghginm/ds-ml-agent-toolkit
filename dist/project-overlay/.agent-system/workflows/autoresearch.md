# Autoresearch workflow

## Trigger and controls

Use when the user explicitly requests autoresearch or clearly authorizes repeated
autonomous experiments against a measurable objective. Do not use for an ordinary
bug fix, explanation, one-shot experiment, or vague request to improve a model.

| Parameter | Default |
| --- | --- |
| selection objective | Infer optimization wording; keep business/reporting metrics separate |
| experiment mode | `benchmark` for predeclared sweeps; `adaptive` for evidence-driven sequences |
| `max experiments` | 10 cheap local experiments |
| editable scope | Smallest repository-supported scope |
| guardrails | Existing tests plus relevant metric/resource constraints |
| final holdout | Never used as the repeated search objective |

## Contract

1. Use the `autoresearch` skill to reconstruct `evaluation.yaml` from the request
   and repository evidence. `.agent-system/tooling/reconstruct-contract.py` performs
   bounded phrase parsing: metric identity stays syntactic, evaluation qualifiers
   such as out-of-sample/OOS/holdout/CV/rolling are separated into evaluation
   design, explicit directions are preserved, and unresolved directions are
   surfaced rather than invented. It binds explicit structural roles generically —
   `Optimize X`, `Selection metric/objective: X, minimize`, `Report X as a
   secondary/business metric`, `Use X as a guardrail`, and `Keep X below/roughly
   flat/within ...` — without knowing any metric's semantics. Show only a compact
   preflight with mode, metric
   roles, evaluation, final-holdout exposure, point-in-time status, budget, and
   guardrails.
2. Obtain confirmation unless the initial request already supplies a complete,
   safe contract and explicitly authorizes immediate execution.
3. Before isolation, run `git_preflight.py --git-mode required` and retain its
   initiating repository root, branch, revision, upstream, remotes, cleanliness,
   and ahead/behind state as `canonical_project_root`. If Git is absent, ask about
   initialization only because autoresearch requires it. Keep the root distinct
   from `experiment_worktree_root` and `toolkit_root`; never recompute it after
   changing directories. Remote checks reuse normal credentials; synchronization
   is fetch/check or clean fast-forward-only, never blind pull, stash, reset,
   merge, or rebase.
4. Initialize evidence with `create-run.py --project-root
   <canonical_project_root> --autoresearch --experiment-mode <mode>`, retain the
   absolute canonical `run_dir`, then isolate user work, reproduce the baseline,
   and freeze the executable evaluation contract.
5. Run the bounded hypothesis → edit → evaluate → decide loop without per-candidate
   approval. Use explicit lifecycle statuses and content-addressed identity;
   duplicate detection reasons over experimental identity — candidate identity
   plus evaluation context — so repeating a candidate in the same context is
   caught before normal budget use (duplicate configs) and after execution
   (duplicate predictions), while the reserved protected re-evaluation of the
   promoted frozen candidate is recognized as a new scientific role, not a
   duplicate. That reuse is mechanically anchored: the stage-`final` row must
   repeat the promoted row's `candidate_identity` with unchanged immutable
   provenance, and the promoted candidate must exist first.
   The baseline establishes the reference and never consumes the novel experiment
   budget; duplicates, crashed, invalid candidates, and the protected final
   evaluation of the already-counted promoted candidate never consume it.
   `record-experiment.py` mechanically enforces that hard ceiling for novel
   candidates with one shared accounting rule used by plateau stopping, run
   counters, and finalization. Protected final evaluation is **one-shot** at
   the managed evaluation boundary. `record-experiment.py
   --run-protected-evaluation ... -- COMMAND` mechanically enforces two
   distinct durable ledger transitions:

       RESERVED       -- the protected population may have been observed
       CONSUMED       -- this run's managed evaluator launch has begun

   Both are appended to `.agent-system/evaluation-ledger.jsonl` BEFORE the
   evaluator subprocess is spawned, so once a managed execution has begun,
   no later `--run-protected-evaluation` invocation for the same run +
   protected population will launch an evaluator again — regardless of
   whether the prior attempt succeeded, crashed, exited non-zero, lost the
   result handoff, never recorded a row, or failed to spawn the process. A
   crashed managed execution leaves the run with no valid untouched final
   estimate for that population; the run must use a new untouched final
   population for another genuinely untouched estimate. When the wrapper is
   not used (manual evaluation invoked after `--reserve-final-exposure`),
   execution-then-reservation order rests on agent discipline; the journal
   can verify the reservation but cannot retroactively prove reservation
   preceded execution. A run records at most one evaluated stage-`final`
   experiment; a repeated protected query against the journal is downgraded
   to a duplicate. Ledger order fixes each run's exposure state at its own
   commit time: a later reservation by another run cannot retroactively
   invalidate an earlier authorized one-shot evaluation, while a run that
   never reserved sees the prior exposure and cannot claim untouched.
   The deterministic boundary covers reservation-before-RECORDING always, and
   reservation-before-EXECUTION for any evaluation run through
   `--run-protected-evaluation`; an evaluator invoked outside the wrapper
   cannot be sequenced by the journal, so always reserve before manually
   invoking any protected evaluator.
6. Write every `run.yaml`, `evaluation.yaml`, `learning.yaml`, and `experiments.tsv` update through
   canonical `run_dir`, never through a path relative to the isolated worktree CWD.
7. Stop at the budget, target, conservative plateau, invalid evaluation, or capability gate.
8. Finalize only with `finalize-run.py`; it revalidates every run — including one
   already marked `finalized` — persists candidate learning events while a run is
   still open even when finalization fails, verifies that every protected
   evaluation already has its committed exposure event (it never creates one),
   and succeeds idempotently on retry with zero writes. Once
   `evidence_status: finalized` is reached, evidence is immutable: normal
   toolkit commands may validate and read it but refuse to mutate it.

Autoresearch may execute in an isolated worktree, but durable run evidence belongs
to the canonical user project root from which the run was initiated. Never use the
isolated worktree or toolkit installation as the sole evidence location. Relative
`.agent-system/runs/...` references are relative to `canonical_project_root`.

Disposable candidate outputs may stay in the isolated worktree, but a final
artifact needed to understand or reproduce the selected result must be copied to
canonical `run_dir` or referenced at a deliberately persistent location. Candidate
source mutations and destructive rollback remain confined to the isolated worktree.

Before completion, verify canonical `run.yaml`, `evaluation.yaml`, `learning.yaml`,
and `experiments.tsv` exist, `journal_ref` is the canonical sibling journal, and
transactional finalization passed. Complete
with baseline/best comparison, experiment
counts, stopping reason, guardrails, retained local revision, uncertainty, and
`Run evidence: .agent-system/runs/<run-id>/`. State honestly whether the
protected final evaluation ran through `--run-protected-evaluation`
(mechanically reserved before execution) or was invoked manually after
`--reserve-final-exposure` (execution-before-reservation is then an
agent-discipline guarantee the journal cannot re-verify).
Material improvement claims go to
independent validation.
