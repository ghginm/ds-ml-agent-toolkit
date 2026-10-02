#!/usr/bin/env python3
"""Reconstruct a draft evaluation contract from a natural-language research request.

This is the request -> evaluation-contract reconstruction layer, deliberately
separate from generic validation. It performs bounded structural phrase parsing
only — the same helper the autoresearch workflow uses; there is no second
parser to drift:

* metric identity stays syntactic (shared canonicalization with the validator);
* evaluation qualifiers such as out-of-sample/OOS/holdout/CV/rolling are
  evaluation-design context, not alternate metric names, and are separated out;
* direction is taken only from explicit wording or from caller-supplied
  repository/project evidence, never invented from a metric name here;
* unresolved directions are surfaced for the preflight instead of guessed.

Understood structural forms (metric names remain opaque in every one of them):

* ``Selection metric: X, minimize`` / ``Selection objective: X, maximize``
* ``Optimize X`` / ``Optimization via X``
* ``Report/track X as a secondary|business|... metric``  -> reporting role
* ``Use X as a guardrail``                               -> guardrail role
* ``Keep X below/roughly flat/within/constant ...``      -> guardrail role
* ``Do not let X regress/degrade/...``                   -> guardrail role
* ``metric=X`` weak mentions                             -> selection fallback
  or secondary reporting mention

Project domain knowledge (for example that a project's "FA" is a maximizing
business metric) is supplied via ``--metric-semantics`` or applied by the
agent/skill; this tool encodes no metric ontology of its own.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_PATH = Path(__file__).resolve()
VALIDATOR_PATH = SCRIPT_PATH.parent / "validate-kit.py"
SPEC = importlib.util.spec_from_file_location("dsml_validate_kit", VALIDATOR_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load validator: {VALIDATOR_PATH}")
validate_kit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validate_kit)

canonical_metric_name = validate_kit._canonical_metric_name

# Evaluation-design vocabulary that may prefix a metric phrase. These qualify
# HOW a metric was computed (holdout/CV/temporal), not WHAT the metric is, and
# apply across DS/ML domains, not only forecasting.
_EVAL_QUALIFIER_PHRASES = {
    "out of sample",
    "out-of-sample",
    "oos",
    "holdout",
    "hold out",
    "cross validated",
    "cross-validated",
    "cross validation",
    "cross-validation",
    "cv",
    "rolling origin",
    "rolling-origin",
    "rolling",
    "temporal",
    "time aware",
    "time-aware",
    "grouped",
    "out of fold",
    "out-of-fold",
    "oof",
}
_METRIC_PHRASE_RE = r"([^\n.;]+)"

# A weak `metric=...` mention stops at punctuation, a line end, or a role
# clause such as "with optimization via ...", so a reporting mention is never
# glued onto the following selection clause.
_WEAK_METRIC_RE = (
    r"\bmetric\s*[:=]\s*([A-Za-z][A-Za-z0-9 _@./-]*?)"
    r"(?=[,.;\n]|\s+(?:with|plus|including|and)\b|\s*$)"
)

_SELECTION_FORMS = (
    re.compile(
        r"selection\s+(?:metric|objective)\s*[:=]\s*" + _METRIC_PHRASE_RE,
        re.IGNORECASE,
    ),
    re.compile(
        r"\boptimi[sz]ation\s*(?:should\s+be\s+done\s+)?(?:via|by|to|:)\s+"
        + _METRIC_PHRASE_RE,
        re.IGNORECASE,
    ),
    # "Optimize cross-validated AUROC" — imperative selection declaration.
    re.compile(r"\boptimi[sz]e\s+" + _METRIC_PHRASE_RE, re.IGNORECASE),
)

_REPORTING_ROLE_WORDS = {
    "secondary",
    "business",
    "reporting",
    "supporting",
    "diagnostic",
    "monitoring",
    "contextual",
    "metric",
    "measure",
    "indicator",
    "kpi",
}

# Role clauses bind a metric phrase to an explicit contract role using only
# structural wording; no metric semantics are consulted.
_ROLE_FORMS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"\b(?:use|uses|used|hold|holds|treat|treats)\s+([^\n.;]+?)\s+as\s+"
            r"(?:a\s+|an\s+)?guardrail\b",
            re.IGNORECASE,
        ),
        "guardrail",
    ),
    (
        re.compile(
            r"\bkeep\s+([^\n.;]+?)\s+(?:below|above|under|within|at\s+(?:most|or)\b|"
            r"no\s+more\s+than|roughly\s+flat|flat\b|constant|stable|the\s+same)\b",
            re.IGNORECASE,
        ),
        "guardrail",
    ),
    (
        re.compile(
            r"\b(?:do\s+not\s+let|don't\s+let|without\s+letting|prevent)\s+"
            r"([^\n.;]+?)\s+(?:regress|degrades?|worsens?|drops?|falls?|increases?|rises?)\b",
            re.IGNORECASE,
        ),
        "guardrail",
    ),
    (
        re.compile(
            r"\b(?:report|reports|track|tracks|surface|surfaces|display|displays)\s+"
            r"([^\n.;]+?)\s+as\s+([^\n.;]+)",
            re.IGNORECASE,
        ),
        "report_by_tail",
    ),
)


def _split_qualifiers(collapsed: str) -> tuple[list[str], str]:
    """Strip leading evaluation qualifiers, returning them and the bare metric words."""
    qualifiers: list[str] = []
    words = collapsed.split(" ")
    changed = True
    while changed and words:
        changed = False
        for span in (3, 2, 1):
            if len(words) > span:
                head = " ".join(words[:span]).lower()
                if head in _EVAL_QUALIFIER_PHRASES:
                    qualifiers.append(head)
                    words = words[span:]
                    changed = True
                    break
            elif len(words) == span:
                head = " ".join(words).lower()
                if head in _EVAL_QUALIFIER_PHRASES and len(words) > 1:
                    qualifiers.append(head)
                    words = []
                    changed = True
                    break
    return qualifiers, " ".join(words)


def _collapse(phrase: str) -> str:
    return re.sub(r"[\s\-_]+", " ", phrase.strip()).strip()


def _report_role_from_tail(tail: str) -> str:
    """Classify 'report X as <tail>' structurally; unknown tails are not a role claim."""
    words = set(re.findall(r"[a-z0-9]+", tail.lower()))
    if "guardrail" in words:
        return "guardrail"
    if words & _REPORTING_ROLE_WORDS:
        return "reporting"
    return ""


def _decompose(phrase: str) -> tuple[str, str, list[str]]:
    """Return canonical metric identifier, explicit direction, and qualifiers.

    Evaluation qualifiers are separated from metric identity so ``OOS RMSE``
    and ``out-of-sample RMSE`` reconstruct to the metric ``rmse`` with
    ``oos``/``out of sample`` recorded as evaluation-design context. Only
    explicit direction wording is preserved; nothing is inferred from the name.
    """
    match = re.search(r"\b(minimi[sz]e|maximi[sz]e)\b", phrase, re.IGNORECASE)
    direction = ""
    if match is not None:
        direction = "minimize" if match.group(1).lower().startswith("minimi") else "maximize"
    stripped = re.sub(r"\b(minimi[sz]e|maximi[sz]e)\b", " ", phrase, flags=re.IGNORECASE)
    # A metric phrase ends at its first comma: following comma clauses are
    # separate constraints, budgets, or role sentences ("PR-AUC, max 15
    # experiments"), never part of metric identity.
    stripped = stripped.split(",")[0]
    stripped = re.sub(r"[.;]", " ", stripped)
    qualifiers, bare = _split_qualifiers(_collapse(stripped))
    return canonical_metric_name(bare), direction, qualifiers


def reconstruct(request: str, metric_semantics: dict[str, Any] | None = None) -> dict[str, Any]:
    """Extract candidate contract fragments from documented lean prompt forms.

    Returns a draft contract with unresolved semantics left explicitly empty;
    generic validation then enforces the final explicit contract.
    """
    semantics = metric_semantics or {}
    selection_claims: list[tuple[str, str, list[str]]] = []
    for form in _SELECTION_FORMS:
        for match in form.finditer(request):
            metric, direction, claim_qualifiers = _decompose(match.group(1))
            if not metric:
                continue
            selection_claims.append((metric, direction, claim_qualifiers))
    role_mentions: list[tuple[str, str, list[str], str]] = []
    for pattern, role in _ROLE_FORMS:
        for match in pattern.finditer(request):
            phrase = match.group(1)
            mention_role = role
            if role == "report_by_tail":
                mention_role = _report_role_from_tail(match.group(2))
                if not mention_role:
                    continue
            metric, direction, mention_qualifiers = _decompose(phrase)
            if metric:
                role_mentions.append((metric, direction, mention_qualifiers, mention_role))
    weak_mentions: list[tuple[str, str, list[str]]] = []
    for mention in re.findall(_WEAK_METRIC_RE, request, re.IGNORECASE):
        metric, direction, mention_qualifiers = _decompose(mention)
        if metric:
            weak_mentions.append((metric, direction, mention_qualifiers))

    if len({metric for metric, _, _ in selection_claims}) > 1:
        raise ValueError(
            "conflicting selection directives: "
            + ", ".join(sorted({metric for metric, _, _ in selection_claims}))
        )

    selection_metric = ""
    selection_direction = ""
    qualifiers: list[str] = []
    if selection_claims:
        selection_metric, selection_direction, claim_qualifiers = selection_claims[0]
        qualifiers = list(claim_qualifiers)
        for _metric, direction, claim_qualifiers in selection_claims[1:]:
            if not selection_direction and direction:
                selection_direction = direction
            qualifiers.extend(claim_qualifiers)
    elif weak_mentions:
        distinct_weak = sorted({metric for metric, _, _ in weak_mentions})
        if len(distinct_weak) == 1:
            selection_metric = distinct_weak[0]
            selection_direction = next(
                (direction for metric, direction, _ in weak_mentions if metric == selection_metric),
                "",
            )
            qualifiers = [
                item
                for metric, _, mention_qualifiers in weak_mentions
                if metric == selection_metric
                for item in mention_qualifiers
            ]
        else:
            raise ValueError(
                "request is ambiguous about the selection metric: "
                + ", ".join(distinct_weak)
            )
    if not selection_metric:
        raise ValueError("request does not identify a selection metric")

    unresolved: list[str] = []
    selection_semantics = semantics.get(selection_metric, {})
    direction = selection_direction or selection_semantics.get("direction", "")
    if not direction:
        unresolved.append(selection_metric)

    # Secondary metrics: explicit role clauses first, then unselected weak
    # mentions (which default to reporting). One entry per canonical metric;
    # an explicit structural role wins over the weak default.
    secondary_by_metric: dict[str, dict[str, Any]] = {}
    for mention, mention_explicit_direction, mention_qualifiers, mention_role in role_mentions:
        if mention == selection_metric:
            continue
        qualifiers = qualifiers + mention_qualifiers
        entry = secondary_by_metric.get(mention)
        mention_semantics = semantics.get(mention, {})
        if entry is None:
            # Explicit structural role wording from the user wins over any
            # repository evidence role; semantics only fill direction and
            # tolerance gaps.
            secondary_by_metric[mention] = {
                "metric": mention,
                "role": mention_role,
                "direction": mention_explicit_direction or mention_semantics.get("direction", ""),
                "max_degradation": mention_semantics.get("max_degradation"),
            }
        else:
            if mention_role == "guardrail":
                entry["role"] = "guardrail"
            if mention_explicit_direction and not entry["direction"]:
                entry["direction"] = mention_explicit_direction

    for mention, mention_explicit_direction, mention_qualifiers in weak_mentions:
        if mention == selection_metric or mention in secondary_by_metric:
            continue
        qualifiers = qualifiers + mention_qualifiers
        mention_semantics = semantics.get(mention, {})
        secondary_by_metric[mention] = {
            "metric": mention,
            "role": mention_semantics.get("role", "reporting"),
            "direction": mention_explicit_direction or mention_semantics.get("direction", ""),
            "max_degradation": mention_semantics.get("max_degradation"),
        }

    secondary_metrics = list(secondary_by_metric.values())
    for entry in secondary_metrics:
        if not entry["direction"]:
            unresolved.append(entry["metric"])

    draft = {
        "selection_objective": {
            "metric": selection_metric,
            "direction": direction,
            "minimum_meaningful_delta": None,
        },
        "secondary_metrics": secondary_metrics,
        "evaluation_qualifiers": sorted(set(qualifiers)),
        "unresolved_directions": unresolved,
        "note": (
            "Draft from request phrases plus supplied repository evidence; the "
            "agent must resolve unresolved directions with the repository or the "
            "user before writing evaluation.yaml. Generic validation never infers "
            "direction from a metric name. Guardrail-role entries additionally "
            "require an explicit max_degradation tolerance before the contract is valid."
        ),
    }
    return draft


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--request", help="natural-language research request text")
    source.add_argument("--request-file", type=Path, help="file containing the request")
    parser.add_argument(
        "--metric-semantics",
        type=Path,
        help=(
            "optional JSON object of project/repository metric evidence keyed by "
            "canonical metric identifier: {\"<metric>\": {\"direction\": ..., \"role\": ...}}"
        ),
    )
    args = parser.parse_args()
    try:
        request = (
            args.request
            if args.request is not None
            else args.request_file.read_text(encoding="utf-8")
        )
        semantics = None
        if args.metric_semantics is not None:
            loaded = json.loads(args.metric_semantics.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError("metric semantics evidence must be a JSON object")
            semantics = loaded
        draft = reconstruct(request, semantics)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED: {exc}")
        return 1
    print(json.dumps(draft, indent=2))
    if draft["unresolved_directions"]:
        print(
            "UNRESOLVED: metric direction(s) not established — surface in preflight: "
            + ", ".join(draft["unresolved_directions"])
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
