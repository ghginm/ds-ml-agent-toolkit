# Validation findings

## Verdict

**Verdict:** `PASS`, `PASS_WITH_UNCERTAINTY`, `REQUIRES_CHANGES`, `NOT_VERIFIED`, or `BLOCKED`

State the supported decision, highest-impact finding, and review boundary in a few sentences. `PASS_WITH_UNCERTAINTY` is never deployment or production approval.

## Review provenance

| Item | Evidence |
| --- | --- |
| Original request and acceptance | Reference or concise reconstruction |
| Repository revision and diff | Exact identifiers or unavailable reason |
| Raw run/test/metric artifacts | Sanitized references |
| Reviewer independence | Independent agent, independent person, or logically separated sequential pass |
| Checks unavailable | Capability, authorization, or missing-artifact boundary |

## Central claims and falsification

| Claim | Counterexample sought | Check actually run | Result | Verdict effect |
| --- | --- | --- | --- | --- |
| Acceptance-critical claim | Plausible invalidating mechanism | Command/evidence reference or unavailable reason | Verified observation | Consequence |

## Material findings

### Concise finding title

- **severity:** `BLOCKER`, `HIGH`, `MEDIUM`, or `LOW`
- **claim:** The reviewed statement or behavior.
- **evidence:** Source, artifact, or command result actually inspected.
- **failure_mechanism:** How the claim can fail or why it is unsupported.
- **impact:** Effect on the supported decision.
- **required_action:** Smallest concrete correction or missing check.
- **verification_status:** `verified`, `partially_verified`, `not_verified`, or `blocked`.

Repeat only for material findings; remove this section if none remain.

## Checks actually run

List exact sanitized commands/checks and outcomes. Do not mix recommended checks into this section.

## Required actions and residual uncertainty

Prioritize the smallest actions needed to change the verdict. State unavailable checks and their impact separately from known defects.