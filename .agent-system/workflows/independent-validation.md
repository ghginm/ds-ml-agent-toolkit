# Independent validation workflow

## Trigger and controls

Use for `Independently validate...` or an equally explicit request for a separate
adversarial review. Routine developer checks remain ordinary work.

| Parameter | Default |
| --- | --- |
| `focus` | Claims whose failure changes the supported decision |
| evidence | Original request, raw artifacts, revisions, commands, and results |
| mutation | Read-only with respect to product code |

## Contract

1. Use `validate-dsml-result`; reconstruct acceptance criteria from original
   evidence rather than the author's narrative.
2. Identify central claims and attempt the highest-value counterexample or
   alternative explanation for each relevant review surface.
3. Record material findings, checks actually run, unavailable checks, and one
   supported verdict.
4. Hand required fixes back to normal implementation; revalidate affected claims
   after correction.

Complete only when central claims received a meaningful falsification attempt and
the verdict is traceable to evidence. Missing evidence yields uncertainty,
`NOT_VERIFIED`, or `BLOCKED`—never a fabricated pass.
