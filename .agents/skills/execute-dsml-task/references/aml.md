# AML extension

Load only for an actual anti-money-laundering or closely related financial-crime project. Treat these as risk surfaces to verify against project evidence, not claims about the organization.

## Contract checks

- Split by time and, where the decision generalizes across parties or networks, by relevant entity/connected component. Random row splits can leak entity behavior.
- Record label source, observation/maturation window, adjudication delay, censoring, noise, and whether labels encode prior model or investigator selection.
- Evaluate extreme imbalance with decision-relevant metrics. Include precision/recall at fixed alert volume or investigator capacity when alerts are the operational output.
- Distinguish model detection metrics from investigation outcomes, reporting behavior, and downstream case disposition.
- Check threshold and calibration stability over time and across material customer/product/geography/channel segments permitted by policy.
- Measure typology and segment coverage; an aggregate gain may hide loss of a critical behavior.
- Trace household, account, device, counterparty, graph, or investigator-derived features for entity/time leakage and point-in-time availability.
- Compare candidate alert volume, overlap, and incremental yield with the baseline under the same matured-label population.

## Evidence boundary

Internal typologies, alert logic, case narratives, customer data, and reporting information may be highly sensitive. Use only approved tools and sanitized aggregates. Do not put raw rows, identifiers, narratives, or confidential logic in generated artifacts. An assistant's domain familiarity is not organizational evidence; identify the approved repository source or subject-matter reviewer.

## Completion check

State label maturity, time/entity split, alert-capacity assumption, threshold/calibration behavior, segment/typology coverage, and the gap between model metrics and operational outcomes. Mark inaccessible checks explicitly and do not convert uncertainty into approval.