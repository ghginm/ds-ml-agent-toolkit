# DS/ML Agent Skills Toolkit — source repository

This repository develops, tests, versions, and releases the `dsml-agent-kit`. Maintainers work here; data scientists using the toolkit in another repository should start with [`dist/project-overlay/.agent-system/CONTROL.md`](dist/project-overlay/.agent-system/CONTROL.md).

The maintained core remains three harness-neutral, progressively disclosed skills:

- `analyze-dsml-project` — project orientation, data-to-decision tracing, technical reporting, and explicit audit;
- `execute-dsml-task` — concrete diagnosis, implementation, and model experimentation;
- `validate-dsml-result` — read-only adversarial validation of decision-relevant results.

The toolkit also bundles `compose-dsml-report` for controlled technical-report synthesis and `autoresearch` for repeated measurable optimization. They are specialized skills, not additional core skills; project-specific skills remain supported.

## Source and distribution

```text
maintained source implementation
        ↓  tooling/build-overlay.py
deterministic validation and build
        ↓
dist/project-overlay/
        ↓  copy/merge without destructive overwrite
target DS/ML/AML repository
```

The source tree includes evals, tests, toolkit-development policy, maintenance history, and build tooling. The overlay contains released runtime skills, three explicit workflow contracts, `CONTROL.md`, `SYSTEM.md`, the small project template, thin adapters, and consumed schemas/tooling. The build uses an explicit copy manifest and writes hashes to `.agent-system/manifest.json`; source validation fails when checked-in distribution content drifts.

## Repository structure

- [`.agents/skills/`](.agents/skills/) — the three core skills, bundled specialized skills, and their progressively loaded references/assets.
- [`.agent-system/`](.agent-system/) — source policy, runtime templates/schemas, project template, toolkit-development run history, and learning-signal contracts.
- [`adapters/`](adapters/) — thin harness discovery and instruction-merge fragments.
- [`evals/`](evals/) — synthetic behavioral cases, fixtures, and observable rubrics.
- [`tooling/build-overlay.py`](tooling/build-overlay.py) — deterministic overlay builder.
- [`tooling/validate-kit.py`](tooling/validate-kit.py) — source, overlay, and installed-project validation modes.
- [`tests/`](tests/) — mutation, build, drift, schema, and synthetic installed-project tests.
- [`dist/project-overlay/`](dist/project-overlay/) — generated release content copied into a target project.
- [`VERSION`](VERSION) — current source release version; the build copies it to `.agent-system/VERSION` in the overlay.

## Development workflow

```text
inspect current behavior and consumers
→ implement the smallest coherent change
→ add or update a reproducing test/eval
→ build the overlay
→ validate source and overlay
→ run unit tests
→ inspect the generated overlay and final diff
→ obtain human review
→ release the next version
```

Do not rewrite working skills for style, add dependencies when the standard library is sufficient, or move harness-specific behavior into the core. Use only synthetic, non-sensitive eval data.

## Adding or changing a skill

The released toolkit always has exactly three core skills plus the expected bundled specialized skills, while an installed project may add project-specific skills. Source validation enforces:

```text
source_skills == core_skills ∪ bundled_specialized_skills
```

Installed-project validation enforces:

```text
core_skills ∪ bundled_specialized_skills ⊆ installed_skills
```

Create a separate skill only after repeated real usage shows distinct triggers, a distinct workflow, reusable task/domain instructions, and enough independent logic to reduce irrelevant context. Otherwise prefer an existing reference, project context, ordinary agent reasoning, or a small repository instruction.

Shipped skill frontmatter requires portable `name`, `description`, `license`, and string `metadata.author`/`metadata.version`. Core descriptions additionally preserve their role boundaries. A project extension needs valid skill frontmatter and a meaningful non-conflicting workflow, but does not inherit source-only toolkit metadata requirements.

For a maintained skill change:

1. add or update a synthetic routing/procedure case;
2. preserve non-trigger coverage and neighboring workflows;
3. change the narrowest skill/reference layer;
4. rebuild and run all validation;
5. require human review before release.

## Project configuration and capability policy

`.agent-system/project.template.yaml` holds only stable agent-relevant facts that cannot be cheaply or reliably recovered from authoritative repository files. New setup does not persist detected names, commands, source paths, or tools. Optional fields and `null` values are valid; the schema accepts legacy discovery fields so existing installed projects remain readable.

Capability decisions remain in the reviewed capability policy, not in reusable skills. The portable template is conservative. An approved active project policy may classify a recurring bounded action as allowed so the agent does not request the same approval repeatedly. Organization and repository prohibitions always win, and authorization never expands beyond the recorded scope.

## Setup lifecycle

The deployed user starts with `.agent-system/CONTROL.md` and says `Set up the DS/ML Agent Kit`. Setup routes through `analyze-dsml-project` orientation mode. The deployed `.agent-system/tooling/onboard-project.py` helper reports transient repository detections, preserves project-owned state, applies conservative capability semantics, invokes installed-project validation, and writes `.agent-system/onboarding-status.md`. `.agent-system/SYSTEM.md` documents architecture and the three contracts in `.agent-system/workflows/`; neither file duplicates skill procedure.

Behavioral onboarding cases live in `evals/cases/behavioral-cases.json`; deterministic first-run, preservation, failure, permission, validation-unavailable, recheck, and synthetic end-to-end coverage lives in `tests/test_onboarding.py`. Change maintained source files first, rebuild the overlay, then validate source, overlay, and installed-project behavior. Generated onboarding status and project configuration belong to target projects and are intentionally absent from the clean overlay.

## Run evidence and learning metadata

Each new tracked run has two sibling records. `run.yaml` remains the detailed task/project evidence trail; `learning.yaml` contains only compact request classification, actual routing, and zero or more meaningful project- or kit-scoped signals. Empty signals are expected for ordinary work, while request metadata is always retained for later cross-run pattern discovery. Historical run-only records remain valid.

Each `learning.yaml` also records the day of the run and the toolkit version that produced it, so future analysis can correlate signals with releases. Signals may carry a single `evidence_ref` pointing to the relevant `run.yaml` section when the link adds value.

The future collection and improvement lifecycle is documented in [`.agent-system/docs/LEARNING_LOOP.md`](.agent-system/docs/LEARNING_LOOP.md). It will aggregate learning records, cluster and deduplicate themes, propose the narrowest responsible change, and require evals plus human acceptance. No collector, learning agent, or automatic instruction modification exists in this release.

## Validation and release

Build or refresh the generated overlay:

```text
python3 -B tooling/build-overlay.py
```

Run source validation, which checks the three core skills plus bundled specialized skills, source policy/contracts, evals, hygiene, and overlay drift:

```text
python3 -B tooling/validate-kit.py --source
```

Validate the generated distribution independently:

```text
python3 -B tooling/validate-kit.py --overlay dist/project-overlay
```

Run unit and synthetic installed-project coverage:

```text
python3 -B -m unittest discover -s tests -v
```

Inside a target project containing the copied overlay:

```text
python3 -B .agent-system/tooling/validate-kit.py --installed-project .
```

Overlay validation rejects undeclared files and corrupted released resources. Installed-project validation hashes only toolkit-owned files, requires the three core skills and bundled specialized skills including controlled report composition, validates optional project configuration and learning records, allows project-specific skills, and ignores unrelated application code, documentation, markers, and symlinks.

Before release, manually inspect `dist/project-overlay/` as the complete user package. Confirm that it contains no source README, evals, tests, development runs, active source policy, or other maintenance artifacts.

## Versioning

Use lightweight semantic pre-1.0 releases (`0.1.0` through `0.5.0`). Update `VERSION` and shipped skill metadata together, add reproducing evals for behavioral changes, rebuild the overlay, run every validation command above, inspect the distribution, and obtain human review. Historical run metadata remains at the version that produced it.
