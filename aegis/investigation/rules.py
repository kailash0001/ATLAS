"""Deterministic hypotheses, never a claim that correlation proves root cause."""

RULES_VERSION = "1"
STEPS = {
    "inspect_source": "Inspect upstream sensors, schema and source delivery before model changes.",
    "validate_data": "Validate a fresh representative data batch against the saved policy.",
    "review_drift": "Review changed feature distributions and their collection process.",
    "review_segments": "Compare forecast errors by hour and validate recent occupancy inputs.",
    "review_model": "Compare validated recent outcomes against reference performance.",
    "consider_retraining": (
        "Consider a retraining request using validated recent data, "
        "subject to approval and quality gates."
    ),
    "inspect_runtime": "Inspect latency, errors and resources in the affected window.",
    "inspect_deployment": "Compare deployed versions and the rollout timeline.",
    "collect_telemetry": "Collect missing runtime and deployment evidence for this window.",
    "collect_labels": "Collect enough verified outcomes to measure performance.",
}


def classify(bundle):
    facts = bundle["facts"]
    categories = []
    matched = []

    def match(rule, category, kinds, steps):
        support = [f["id"] for f in facts if f["type"] in kinds]
        if support:
            categories.append(category)
            matched.append(
                {"rule": rule, "category": category, "supporting_facts": support, "steps": steps}
            )

    match(
        "source-contract",
        "UPSTREAM_SYSTEM",
        {"SCHEMA_CHANGE", "OUT_OF_RANGE_FEATURE", "UPSTREAM_DATA_FAILURE"},
        ["inspect_source", "validate_data"],
    )
    # An empty sample is not proof of an upstream outage.
    missing = [f for f in facts if f["type"] == "MISSING_DATA" and "fraction" in f["measurement"]]
    if missing and "UPSTREAM_SYSTEM" not in categories:
        categories.append("UPSTREAM_SYSTEM")
        matched.append(
            {
                "rule": "missing-values",
                "category": "UPSTREAM_SYSTEM",
                "supporting_facts": [f["id"] for f in missing],
                "steps": ["inspect_source", "validate_data"],
            }
        )
    match("deployment-regression", "DEPLOYMENT", {"DEPLOYMENT_REGRESSION"}, ["inspect_deployment"])
    match(
        "runtime-degradation",
        "INFRASTRUCTURE",
        {"LATENCY_DEGRADATION", "ERROR_RATE_SPIKE", "RESOURCE_EXHAUSTION"},
        ["inspect_runtime"],
    )
    match("feature-distribution", "DATA", {"DATA_DRIFT"}, ["review_drift", "validate_data"])
    match("observed-performance", "MODEL", {"PERFORMANCE_DEGRADATION"}, ["review_model"])
    # Prediction drift alone cannot distinguish data changes from model changes.
    primary = categories[0] if categories else "UNKNOWN"
    steps = list(dict.fromkeys(step for rule in matched for step in rule["steps"]))
    if bundle["performance"].get("current", {}).get("by_hour"):
        steps.append("review_segments")
    permitted = (
        bundle["retraining_eligible"]
        and primary in {"DATA", "MODEL"}
        and not {"UPSTREAM_SYSTEM", "INFRASTRUCTURE", "DEPLOYMENT"} & set(categories)
    )
    if permitted:
        steps.append("consider_retraining")
    if bundle["performance"].get("current", {}).get("status") != "evaluated":
        steps.append("collect_labels")
    steps.append("collect_telemetry")
    return {
        "category": primary,
        "contributing_categories": list(dict.fromkeys(categories)),
        "certainty": "supported_hypothesis" if matched else "insufficient_evidence",
        "matched_rules": matched,
        "retraining_eligible": bool(permitted),
        "steps": list(dict.fromkeys(steps)),
        "automatic_action": "NONE",
    }


def explain(bundle, conclusion, fact_ids=None, step_ids=None):
    selected = {f["id"]: f for f in bundle["facts"]}
    fact_ids = list(selected) if fact_ids is None else fact_ids
    step_ids = conclusion["steps"] if step_ids is None else step_ids
    lines = [
        f"Incident {bundle['incident_id']} for {bundle['model']['name']} "
        f"v{bundle['model']['version']}: {bundle['severity']}.",
        f"Likely category: {conclusion['category']} ({conclusion['certainty']}).",
        "These are evidence-supported hypotheses, not proof of causation.",
    ]
    for key in fact_ids:
        fact = selected[key]
        lines.append(f"[{key}] {fact['summary']}")
    lines.append("Missing evidence: " + "; ".join(bundle["limitations"]) + ".")
    lines.extend(f"Next: {STEPS[step]}" for step in step_ids)
    lines.append("No operational action was executed.")
    return "\n".join(lines)
