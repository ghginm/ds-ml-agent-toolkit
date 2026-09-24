# Synthetic Weekly Demand Forecasting - Technical Assessment

<!-- dsml-report-state-revision: 2 -->
<!-- dsml-report-plan-revision: 2 -->

## Executive Overview

This report assesses the synthetic weekly demand forecasting fixture with emphasis on model design, features, evaluation, and current issues. The implemented path is coherent: cutoff-safe weekly history is transformed into lag, rolling, calendar, and static signals; LightGBM, AutoETS, and a seasonal-naive baseline are candidates; a validation router selects a model; and the output supports a 12-week planning decision.

Three conclusions matter most:

- **Verified performance:** LightGBM improves WAPE over seasonal naive at both reported horizons: 0.22 versus 0.31 at four weeks, and 0.29 versus 0.39 at twelve weeks. This is project-specific empirical support for the fitted LightGBM system on the fixed 2025 Q2 holdout, not proof that every feature or the router adds value.
- **Mechanism and limit:** the global tree model can pool evidence across 420 series and learn nonlinear interactions among recent demand, seasonality, and descriptors. That rationale is technically plausible, but the available artifacts do not isolate which feature families cause the lift.
- **Main validity issue:** model selection uses four weeks while operations consume twelve. Because candidate rankings can change with horizon, optimizing the short window may select the wrong model for the full decision. The fixture reports twelve-week metrics, but it does not show that routing itself was selected and evaluated on independent observations.

The current evidence supports retaining LightGBM as the baseline. It does not yet support a stronger claim that routing is unbiased, that AutoETS adds stable incremental value, or that the feature set is minimal. The highest-information next steps are to align selection with the 12-week objective, evaluate the routed policy on an untouched temporal sample, and run grouped feature ablations on that frozen design.

### Claim discipline

| Claim type | Example in this report | Interpretation |
| --- | --- | --- |
| Verified project fact | Lag 1 has gain importance 41; lag 52 has 35 | The artifact records predictive split gain |
| Technical rationale | Lag 52 may expose annual recurrence directly | Plausible mechanism, not measured contribution |
| Project-specific empirical support | LightGBM WAPE is 0.29 versus 0.39 at 12 weeks | Observed comparative result on the supplied holdout |
| Unknown | Router lift on an independent period | No supporting artifact is present |

## PART I - Understand the Project

### System and decision context

The system predicts weekly demand for each store-item series over a 12-week planning horizon. The fixture covers 420 series from January 2022 through June 2025. The fixed 2025 Q2 holdout is the main reported evaluation period. Demand is missing in 3.1% of rows and equals zero in 18%, so aggregate accuracy combines regular, sparse, and potentially interrupted demand regimes.

| Stage | Verified implementation | Why it matters |
| --- | --- | --- |
| Inputs | Weekly demand, calendar context, and stable descriptors | Defines information available at each cutoff |
| Features | Raw lags, rolling summaries, calendar variables, descriptors | Represents temporal state and cross-series heterogeneity |
| Candidates | LightGBM, AutoETS, seasonal naive | Offers global nonlinear, local statistical, and simple seasonal biases |
| Selection | Validation router using a four-week selection view | Converts candidate comparisons into the deployed policy |
| Evaluation | WAPE and bias at four and twelve weeks; per-origin LightGBM WAPE | Tests aggregate accuracy, direction, and some temporal variation |
| Consumer | Twelve-week planning process | Makes long-horizon behavior operationally relevant |

- **Pooling mechanism:** one global LightGBM model sees examples from many series, which can stabilize learning when individual histories are short or noisy. This should help when series share response patterns that descriptors and temporal features can express.
- **Heterogeneity condition:** pooling helps only if the model can distinguish persistent series differences. Weak or stale descriptors can cause unlike series to share predictions, while very sparse groups may contribute too little signal for reliable local behavior.
- **Forecast-state condition:** lagged demand is known at the forecast origin, but multi-step use depends on the inference design. The fixture does not establish whether later horizons are direct, recursively updated, or horizon-conditioned, so error-propagation claims remain conditional.
- **Decision implication:** the correct unit of confidence is not one aggregate number. The planner consumes a trajectory, so performance by horizon, origin, and demand regime is needed to know where the system is reliable.

### Data, target, and evidence boundaries

The project description establishes weekly store-item demand and a temporal holdout. It does not provide row-level values in this repository snapshot; `eval/predictions.csv` is described as containing predictions, but the fixture exposes only that description. Consequently, this report can interpret the supplied aggregates but cannot independently recompute them, inspect distribution tails, or verify every join and cutoff.

- **Missingness:** 3.1% missing demand may represent absent observations, delayed feeds, non-trading weeks, or true unknown labels. Each mechanism implies a different treatment. Without the missingness rule, it is unknown whether the model learns demand behavior or data-availability behavior.
- **Zeros:** 18% zero demand makes WAPE preferable to per-row percentage errors that can explode at zero actuals. Yet zeros can reflect genuine no-demand periods, stockouts, or assortment gaps. Those cases have different forecasting meaning and may need cohort diagnostics.
- **Temporal stability:** the three reported LightGBM origins have WAPE 0.20, 0.28, and 0.23. The 0.08 range is direct evidence that performance varies over time, although three origins are too few to characterize a stable distribution.
- **Population coverage:** aggregate metrics do not reveal whether large-volume series dominate WAPE or whether sparse series fail disproportionately. This matters because pooling can improve the total while leaving operationally important cohorts weak.
- **Evidence boundary:** descriptions of source files verify intended surfaces, not the numerical contents of files that were not actually supplied. Any conclusion requiring row-level recomputation remains unknown.

### Feature design: signal, conditions, and evidence

The feature-importance artifact (FEAT-IMP-01) assigns gain 41 to lag 1, 35 to lag 52, 15 to a four-week rolling mean, and 9 to calendar features. Gain describes how the fitted trees used variables; it does not measure causal or incremental contribution. The ranking is useful for prioritizing checks, but not for declaring that a family improves out-of-sample performance. FEAT-01 captures the resulting evidence gap: no grouped ablation establishes incremental contribution.

| Family | Verified representation | Intended signal | Empirical status |
| --- | --- | --- | --- |
| Recent state | Lag 1 | Latest observed demand level | Highest gain; no ablation |
| Annual state | Lag 52 | Same-season historical demand | Second-highest gain; no ablation |
| Local level | Rolling mean 4 | Smoothed recent demand | Moderate gain; no ablation |
| Calendar | Calendar variables | Seasonal timing and events | Lower gain; no grouped test |
| Static descriptors | Present in pipeline description | Persistent cross-series differences | Usage effectiveness not measured |

#### Raw lags

- **Short-lag mechanism:** lag 1 exposes the most recent state directly. Tree models do not otherwise know temporal order, so an explicit lag allows splits on current level and recent discontinuities. It should help when weekly demand has short-term autocorrelation.
- **Seasonal-lag mechanism:** lag 52 gives direct access to the corresponding annual period. This should help when recurring demand is aligned to the weekly calendar and year-to-year structure is stable.
- **Horizon interaction:** a known lag is strongest near the forecast origin. If later predictions feed future lag features, errors can become inputs and compound; if the system uses direct horizon-specific rows, the failure mechanism differs. The implementation detail is not available, so recursive instability is a risk to verify, not a verified defect.
- **Failure condition:** lags can become misleading after assortment, pricing, promotion, supply, or structural demand changes. A high gain value can persist even when the relationship is unstable across origins.
- **Redundancy:** lag 52 may overlap with calendar timing, while neighboring recent lags and rolling statistics summarize related history. Trees can tolerate correlated predictors, but redundant families add complexity and can make importance unstable.
- **Evidence implication:** the gain ranking shows use, not necessity. A frozen-split grouped ablation is required to establish incremental project contribution.

#### Rolling statistics

- **Mechanism:** the four-week mean compresses several noisy observations into a local-level estimate. It can make the signal more robust when single-week demand is volatile.
- **Responsiveness tradeoff:** smoothing suppresses noise but also delays reaction to genuine level shifts. It should work best when the local level moves more slowly than week-to-week variation.
- **Interaction:** the mean partly duplicates information available through recent raw lags. Its incremental value depends on whether the tree can efficiently reconstruct the same average and whether the sample size supports those extra splits.
- **Evidence:** gain 15 confirms the fitted model used the feature, but no removal experiment shows whether holdout WAPE worsens without it.

#### Calendar variables and descriptors

- **Calendar role:** calendar variables expose timing that is not encoded by unordered rows. They can help a global model share seasonal behavior across series even when an individual series has limited history.
- **Descriptor role:** stable item or store attributes let the global model condition shared patterns on persistent group differences. This can help cold or sparse series when descriptors correlate with demand shape.
- **Staleness risk:** mappings and descriptors can drift as assortments, stores, or categories change. A stale descriptor may confidently pool a series with the wrong peers.
- **Leakage condition:** target or group encodings, if present, must be fitted out of fold and as of the forecast cutoff. The fixture does not verify such encodings, so this is a control requirement rather than a claim that leakage exists.
- **Evidence:** the artifact does not report descriptor importance, cold-start cohorts, or grouped ablations. Their project-specific value is therefore unknown.

### Model architecture and complementarity

The candidate-history evidence (MODEL-TRIAL-01), aggregate metrics (EVAL-METRICS-01), and routing finding (EVAL-02) support different claim types: observed candidate behavior, observed holdout performance, and an unresolved validity question.

| Component | Inductive bias | Regime where it may help | Verified project evidence |
| --- | --- | --- | --- |
| Global LightGBM | Shared nonlinear rules and interactions | Many related series with informative features | Beats seasonal naive at 4 and 12 weeks |
| Local AutoETS | Per-series level, trend, seasonality | Sufficient clean history and stable local dynamics | Higher runtime and few route wins |
| Seasonal naive | Repeats seasonal history | Strong stable seasonality; limited data | Weaker aggregate WAPE, useful reference |
| Validation router | Chooses candidates by observed validation behavior | Stable, repeatable cross-series heterogeneity | Independent routing lift not reported |

- **Global LightGBM:** pooling 420 series increases the effective training sample and trees can capture nonlinear interactions, such as seasonality differing by item type. It may struggle when local dynamics are idiosyncratic, descriptors are weak, or temporal structure shifts beyond the training range.
- **Local AutoETS:** ETS imposes a smoother state-space structure and can extrapolate level or seasonality without a large feature set. It can complement trees on clean, sufficiently long series, but sparse or intermittent histories make local parameter estimates unstable. The experiment history says it is slower and wins few routes, so its inclusion currently has weak empirical support.
- **Seasonal naive:** the baseline has almost no estimation variance and is hard to beat on stable seasonal series. Its weakness is that it cannot adapt intelligently to covariates or changing levels. Because it is transparent, it remains an important diagnostic even when aggregate WAPE is worse.
- **Router mechanism:** a router can exploit stable heterogeneity if some series repeatedly favor different inductive biases. It can instead learn validation noise when candidate margins are small or the selection sample is short.
- **Interaction:** candidate complementarity is a theoretical reason to route, not evidence that routing improves this project. The missing comparison is routed policy versus best single candidate on an untouched later period, including route shares, margins, and switching stability.
- **Operational implication:** AutoETS runtime is justified only if its independent wins are frequent and valuable enough to offset complexity. "Few route wins" points toward simplification, but exact shares and margins are unavailable.

### Evaluation and observed evidence

The horizon metrics (EVAL-METRICS-01) and per-origin results (EVAL-ORIGIN-01) are verified observations. EVAL-01 records the horizon-alignment defect; EVAL-02 records that independent router lift remains unknown.

| Metric | Seasonal naive | LightGBM | Relative LightGBM improvement |
| --- | ---: | ---: | ---: |
| 4-week WAPE | 0.31 | 0.22 | 29% |
| 12-week WAPE | 0.39 | 0.29 | 26% |
| 4-week bias | 0.04 | -0.01 | Direction closer to zero |
| 12-week bias | 0.06 | -0.03 | Direction closer to zero |

The relative improvements are computed from the supplied aggregates. They establish comparative performance on the reported holdout, subject to the fixture's stated split. They do not establish statistical significance, cohort robustness, or routed-policy lift.

- **Horizon degradation:** LightGBM WAPE rises from 0.22 to 0.29, while seasonal naive rises from 0.31 to 0.39. Both weaken at the longer horizon, so long-range uncertainty is a system property rather than evidence of one model failing uniquely.
- **Selection mismatch mechanism:** the chosen candidate is optimized after observing four-week validation performance. If candidate rankings differ later in the horizon, the short objective favors a policy that can be suboptimal for the 12-week consumer.
- **Selector reuse mechanism:** if the router is evaluated on the same series-period observations used to choose routes, observed performance contains both persistent signal and random noise. Selection favors candidates with favorable noise; reusing those observations preserves that advantage and makes routed performance optimistic. The repository snapshot does not establish whether an outer holdout prevents this.
- **Origin variation:** LightGBM per-origin WAPE of 0.20, 0.28, and 0.23 shows material temporal variation. The next analysis should explain the difficult origin rather than reporting only the mean.
- **Metric interpretation:** WAPE weights errors by total actual volume, which is useful for portfolio planning but can hide poor low-volume series. Bias near zero can also conceal offsetting over- and under-forecast cohorts.
- **Uncertainty:** no intervals, repeated-origin distribution, or confidence estimates are supplied. Therefore the report can compare point estimates but cannot quantify how likely the ranking is to persist.

## PART II - Immediate Focus

These issues become material when model-selection, feature-retention, or planning decisions rely on evidence outside the conditions actually tested. The section therefore states both the failure condition and the check that would change the decision.

### 1. Selection objective is shorter than the operating decision (EVAL-01)

- **Mechanism:** the selector observes candidate behavior over four weeks, while the consumer acts over twelve. Models that are strong near the origin can decay differently from models with stable seasonal extrapolation.
- **Evidence:** the fixture explicitly states four-week model selection and reports both four- and twelve-week metrics. LightGBM's WAPE increases by 0.07 across those views.
- **Affected scope:** candidate choice, route assignments, and any claim that the selected policy is optimal for planning.
- **Implication:** twelve-week aggregate evaluation is encouraging, but the selection rule is not aligned to the full operational loss. Refit selection on a horizon-weighted 12-week objective or justify the four-week proxy empirically.

### 2. Independent router lift is not established (EVAL-02)

- **Mechanism:** choosing a candidate after seeing validation outcomes preferentially captures favorable random error. Evaluation on the same outcomes retains that noise.
- **Evidence:** a validation router exists, but the fixture does not expose a separate outer routing holdout, nested origins, route margins, or routed-versus-single-model results.
- **Affected scope:** confidence in routing, the value of AutoETS, and the complexity cost of maintaining multiple candidates.
- **Implication:** routing is theoretically reasonable but project-specific benefit is unvalidated. An untouched later origin or nested temporal evaluation would resolve the uncertainty.

### 3. Feature contribution is inferred from gain, not measured incrementally (FEAT-01)

- **Mechanism:** correlated variables can divide or substitute split gain, and a feature can receive gain without improving out-of-sample decisions.
- **Evidence:** importance values exist, but no family-level ablation is supplied.
- **Affected scope:** claims about why LightGBM wins, confidence in lag and rolling design, and opportunities to simplify inference.
- **Implication:** retain the current set for the baseline, then remove one family at a time on the frozen evaluation design. Do not use importance rank alone as a deletion rule.

### 4. Aggregate results hide cohort behavior (ROBUST-01)

- **Mechanism:** WAPE emphasizes high-volume actuals; zero-heavy or sparse series may contribute little to the denominator while still causing planning failures.
- **Evidence:** 18% of demand is zero and 3.1% is missing, but no cohort error or coverage diagnostic is reported.
- **Affected scope:** claims of uniform usefulness across 420 series and decisions for sparse items.
- **Implication:** report horizon-by-volume, zero-rate, and history-length cohorts before expanding model complexity.

### Immediate low-hanging fruit

1. Recalculate candidate and routed metrics with the same 12-week horizon weights used by planning.
2. Report route share, win margin, switching rate across origins, and runtime per candidate.
3. Add grouped ablations for recent lags, seasonal lag, rolling statistics, calendar variables, and descriptors.
4. Slice WAPE and bias by horizon, origin, volume, zero-rate, and history length.

## PART III - Research & Improvement Map

| ID | Opportunity | Why now | Evidence basis | Next step | Decision enabled |
| --- | --- | --- | --- | --- | --- |
| EVAL-01 | Align selection to operations | Four-week selection may mis-rank 12-week candidates | Explicit horizon mismatch | Use planning-weighted 12-week selection | Keep or change selection objective |
| EVAL-02 | Outer evaluation for routing | Selection noise can inflate reused results | Router present; independence unknown | Add later untouched origin or nested temporal split | Keep router or best single model |
| FEAT-01 | Grouped feature ablation | Gain does not establish incremental value | Importance artifact, no ablation | Remove one family on frozen split | Retain or simplify features |
| MODEL-01 | Quantify ETS value | Higher runtime and few wins may not justify complexity | Trial-history summary | Compare win margins and stable route shares | Keep or remove AutoETS |
| ROBUST-01 | Cohort diagnostics | Aggregate WAPE may hide sparse-series failures | 18% zeros; 3.1% missing | Slice by zero-rate, volume, history | Define guardrails and fallback policy |
| DATA-01 | Clarify missingness semantics | Missing labels may encode pipeline behavior | Missingness profile only | Classify causes and treatment | Trust or revise target preparation |

The map is deliberately diagnostic before algorithmic. The current evidence already identifies decisions that can be resolved with existing outputs or bounded reruns; generic model expansion would add cost without repairing the main validity questions.

## Suggested Next Investigations

### Path A - Establish trustworthy routed performance

Freeze candidate implementations, align selection loss to the 12-week planning objective, and evaluate the resulting routed policy on a later untouched origin. Report routed WAPE and bias against LightGBM, AutoETS, and seasonal naive, plus route margins and switching. This path answers whether architectural complexity earns its place.

### Path B - Explain the global model's lift

On the same frozen split, run grouped ablations and report changes by horizon and cohort. Start with rolling statistics and descriptors because their incremental value is least visible in the current artifact. This path answers whether the feature architecture is compact and robust.

### Path C - Characterize operating risk

Use row-level predictions to inspect the difficult origin and zero-heavy, low-volume, short-history cohorts. Add horizon curves and interval or bootstrap summaries if the data volume supports them. This path answers where the current baseline should be trusted and where a fallback is needed.

These paths are complementary, but sequence matters: establish an independent evaluation boundary before using small metric differences to retain routing or feature complexity.

## Appendix

### Evidence used

- `docs/model.md`: 12-week operational horizon and weekly store-item grain.
- `data/profile.json`: 420 series, January 2022 to June 2025, 3.1% missing demand, 18% zero demand, fixed 2025 Q2 holdout.
- `eval/metrics.csv`: four- and twelve-week WAPE and bias for seasonal naive and LightGBM.
- `eval/per_origin.csv`: LightGBM WAPE and bias for three origins.
- `artifacts/feature_importance.csv`: gain for lag 1, lag 52, rolling mean 4, and calendar.
- `experiments/trials.csv`: LightGBM improvement over seasonal naive; AutoETS higher runtime and few route wins.
- `src/pipeline.py`: transformations, candidate models, validation router, forecast output.
- `runtime/model_share.csv`: described as containing selection and runtime shares; numerical contents are not exposed in the fixture.

### Evidence not available in the fixture

- Row-level predictions for independent recomputation and cohort analysis.
- Exact train, tuning, routing, and outer-holdout date boundaries.
- Direct-versus-recursive inference implementation.
- Router features, thresholds, margins, and independently evaluated lift.
- Family-level ablations or permutation-based contribution checks.
- Missingness causes, imputation rules, join coverage, and descriptor freshness.
- Runtime values, memory profile, and operational service constraints.

### Decision boundaries from current evidence

| Decision | Current answer | Confidence | Evidence needed to change it |
| --- | --- | --- | --- |
| Use LightGBM rather than seasonal naive as the baseline | Yes, for the supplied holdout | High | A later holdout that reverses the ranking |
| Keep the validation router | Undecided | Low | Independent routed-policy lift and stable route margins |
| Keep AutoETS in the candidate set | Undecided, with weak current support | Medium | Enough stable wins to offset runtime and maintenance cost |
| Retain every feature family | Undecided | Low | Frozen-split grouped ablations by horizon and cohort |
| Treat aggregate WAPE as sufficient for operations | No | High | Cohort and horizon diagnostics showing acceptable tails |

This matrix separates actions supported now from decisions that remain open. It also prevents a reasonable theoretical story from becoming an operational commitment without project evidence.

### Metric interpretation notes

- **Relative lift:** the reported 29% and 26% improvements are calculated as `(baseline WAPE - LightGBM WAPE) / baseline WAPE` for the four- and twelve-week aggregates.
- **Volume weighting:** WAPE emphasizes series and periods with more actual demand. That matches many portfolio decisions but does not describe a typical series or protect sparse cohorts.
- **Bias:** values closer to zero indicate less aggregate directional error under the supplied convention. The sign should not be interpreted more deeply without the implementation definition.
- **Uncertainty:** point differences are not confidence intervals. Repeated origins or a resampling design are needed before small candidate margins should control routing or complexity decisions.

### Final confidence statement

Confidence is high that LightGBM outperforms seasonal naive on the supplied aggregate holdout and that performance weakens at the longer horizon. Confidence is medium that the global architecture is appropriate for this multi-series setting because its mechanism is plausible and comparative results are favorable. Confidence is low that routing and every feature family add independent value, because the artifacts needed to isolate those contributions are absent.
