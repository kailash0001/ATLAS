import time

import numpy as np

from aegis.reliability.analysis import performance
from aegis.reliability.workload import load_predictor, score


def evaluate_candidate(settings, config, policy, quality, frame, candidate_info, baseline_info):
    gates = []

    def check(name, passed, **evidence):
        gates.append({"name": name, "passed": bool(passed), "evidence": evidence})

    measured = {}
    for label, info in [("candidate", candidate_info), ("baseline", baseline_info)]:
        predictor = load_predictor(settings, config, info)
        signature = predictor.metadata.signature
        check(
            f"{label}_artifact_and_signature",
            signature is not None and signature.inputs.input_names() == config.features.all,
            model_version_id=info["model_version_id"],
        )
        scored = score(predictor, frame, config)
        metrics = performance(scored, config.target, config.training.threshold, quality)
        check(f"{label}_evaluation_coverage", metrics["status"] == "evaluated", metrics=metrics)
        example = frame[config.features.all].iloc[:1].copy()
        example[config.features.numeric] = example[config.features.numeric].astype(float)
        for _ in range(5):
            predictor.predict(example)
        timings = []
        for _ in range(policy.latency_samples):
            start = time.perf_counter()
            predictor.predict(example)
            timings.append((time.perf_counter() - start) * 1000)
        measured[label] = {
            "metrics": metrics,
            "p95_ms": float(np.percentile(timings, 95)),
            "latency_samples": policy.latency_samples,
        }
    candidate, baseline = measured["candidate"], measured["baseline"]
    c, b = candidate["metrics"], baseline["metrics"]
    if config.is_regression:
        check(
            "maximum_mape",
            c.get("mape_percent", float("inf")) <= policy.maximum_mape_percent,
            actual=c.get("mape_percent"),
            limit=policy.maximum_mape_percent,
        )
        check(
            "mape_nonregression",
            "mape_percent" in c
            and "mape_percent" in b
            and c["mape_percent"] <= b["mape_percent"] * policy.maximum_regression_ratio,
            candidate=c.get("mape_percent"),
            baseline=b.get("mape_percent"),
        )
    else:

        def recall(metrics):
            counts = metrics.get("confusion", {})
            denominator = counts.get("tp", 0) + counts.get("fn", 0)
            return counts.get("tp", 0) / denominator if denominator else 0

        check(
            "minimum_f1",
            c.get("f1", -1) >= policy.minimum_f1,
            actual=c.get("f1"),
            minimum=policy.minimum_f1,
        )
        check(
            "f1_nonregression",
            c.get("f1", -1) >= b.get("f1", 2),
            candidate=c.get("f1"),
            baseline=b.get("f1"),
        )
        check(
            "recall_minimum_and_nonregression",
            recall(c) >= max(policy.minimum_recall, recall(b)),
            candidate=recall(c),
            baseline=recall(b),
            minimum=policy.minimum_recall,
        )
    check(
        "p95_latency",
        candidate["p95_ms"] <= policy.maximum_p95_ms,
        actual=candidate["p95_ms"],
        limit=policy.maximum_p95_ms,
    )
    check(
        "latency_nonregression",
        candidate["p95_ms"] <= baseline["p95_ms"] * policy.maximum_latency_ratio,
        candidate=candidate["p95_ms"],
        baseline=baseline["p95_ms"],
    )
    return {
        "gates": gates,
        "measurements": measured,
        "passed": all(gate["passed"] for gate in gates),
    }
