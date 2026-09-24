# Diagnose mode

Use for a concrete regression, discrepancy, incorrect pipeline behavior, or suspected bug.

## Investigation loop

1. Define the symptom with expected versus observed behavior, affected window/population, relevant versions, first known occurrence, and decision impact.
2. Reproduce the symptom with the smallest permitted command or fixture. If reproduction is unavailable, establish the exact boundary and preserve non-reproducibility as evidence.
3. Rank a small hypothesis set by plausibility and impact. For each hypothesis, identify one check that distinguishes it from alternatives.
4. Follow the relevant surfaces, not every checklist item:
   - data/query version, source grain, keys, filters, null/default behavior, joins, duplicates, and temporal boundaries;
   - target/label construction, entity overlap, split logic, sampling, and leakage;
   - feature definitions, availability time, online/offline defaults, and training-inference skew;
   - metric code, aggregation level, evaluation population, threshold, and baseline artifact;
   - dependency, configuration, environment, and artifact drift.
5. Change one causal variable at a time. Separate the root cause from contributing factors and downstream symptoms.
6. Classify the conclusion:
   - `confirmed`: direct reproduction or decisive counterfactual evidence;
   - `strongly_supported`: competing explanations were materially weakened;
   - `plausible`: consistent but not discriminated;
   - `unresolved`: evidence is missing, contradictory, or non-reproducible.

## Fix boundary

For diagnosis-only, do not modify product code. If a fix is requested and authorized, implement the smallest coherent correction at the violated contract. Add a regression test or deterministic check that fails for the original mechanism and passes for the fix. Check sibling paths that share the same contract without broad refactoring.

## Evidence table

| Hypothesis | Discriminating check | Result | Status |
| --- | --- | --- | --- |
| Concrete mechanism | Exact command, query, or source comparison | Sanitized observation or evidence reference | Supported, weakened, or unavailable |

## Completion check

Report the symptom, failure mechanism, confidence, affected scope, before/after evidence when changed, remaining limitations, and the next authorized check if unresolved. Do not edit a correct implementation merely to produce a diff.