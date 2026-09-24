# AML validation extension

Load only when an AML result supports a material decision. Review sanitized aggregates and approved evidence; never request or retain raw customer rows, case narratives, identifiers, confidential detection logic, or reporting content merely to complete a checklist.

## High-value falsification checks

- Test whether entities, connected components, investigators, or derived network identifiers cross development and validation boundaries.
- Recompute the evaluation on a time split with a documented label-maturation window; quantify censoring from delayed outcomes.
- Hold alert volume or investigator capacity fixed when comparing precision, recall, yield, or typology coverage.
- Check whether sampling, class weighting, or threshold changes make reported metrics operationally incomparable.
- Compare calibration, threshold, alert overlap, incremental yield, and volume across time and permitted material segments.
- Look for aggregate improvement that removes coverage of a critical typology or segment.
- Distinguish prediction quality from investigation disposition or reporting outcomes affected by selection and process.
- Verify point-in-time availability of entity/network and investigator-derived features in the actual inference path.

## Verdict boundary

Use `REQUIRES_CHANGES` when observed split, label-maturity, or capacity defects already invalidate acceptance, even if further evidence is unavailable. Use `PASS_WITH_UNCERTAINTY`, `NOT_VERIFIED`, or `BLOCKED` when the limitation is missing sensitive evidence, matured labels, entity linkage, or authorized operational metrics rather than a demonstrated fixable defect. No toolkit verdict is deployment, reporting, or production approval.