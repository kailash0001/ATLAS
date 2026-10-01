"""Deterministic evidence, independent of orchestration, persistence or vendors."""

import numpy as np
import pandas as pd
from sklearn.metrics import confusion_matrix, f1_score

from aegis.core.config import ModelConfig
from aegis.core.errors import DataIntegrityError
from aegis.data.fraud import canonical, digest
from aegis.reliability.policy import Policy, Severity, highest


def frame_hash(frame: pd.DataFrame) -> str:
    return digest(frame.to_csv(index=False, lineterminator="\n").encode())


def distance(reference: pd.Series, current: pd.Series, numeric: bool) -> float:
    """Numeric empirical KS distance; categorical total variation. No p-value claims."""
    if numeric:
        a, b = np.sort(reference.astype(float)), np.sort(current.astype(float))
        points = np.unique(np.concatenate([a, b]))
        return float(
            np.max(
                np.abs(
                    np.searchsorted(a, points, side="right") / len(a)
                    - np.searchsorted(b, points, side="right") / len(b)
                )
            )
        )
    a, b = (
        reference.astype(str).value_counts(normalize=True),
        current.astype(str).value_counts(normalize=True),
    )
    return float(a.subtract(b, fill_value=0).abs().sum() / 2)


def profile(frame: pd.DataFrame, config: ModelConfig) -> dict:
    result = {}
    for name in config.features.all:
        if name not in frame:
            result[name] = {"missing_column": True}
            continue
        column = frame[name]
        item = {
            "dtype": str(column.dtype),
            "nulls": int(column.isna().sum()),
            "null_fraction": float(column.isna().mean()) if len(column) else None,
        }
        if name in config.features.numeric:
            converted = pd.to_numeric(column, errors="coerce")
            finite = converted[np.isfinite(converted)]
            item["invalid_numeric"] = int((column.notna() & ~np.isfinite(converted)).sum())
            item["statistics"] = (
                {
                    "mean": float(finite.mean()),
                    "std": float(finite.std(ddof=0)),
                    "min": float(finite.min()),
                    "max": float(finite.max()),
                    "p01": float(finite.quantile(0.01)),
                    "p50": float(finite.median()),
                    "p99": float(finite.quantile(0.99)),
                }
                if len(finite)
                else None
            )
        else:
            item["categories"] = {str(k): int(v) for k, v in column.value_counts().items()}
        result[name] = item
    return {"rows": len(frame), "features": result}


def performance(frame: pd.DataFrame, target: str, threshold: float, policy: Policy) -> dict:
    if target == "demand_kw":
        from aegis.reliability.regression import performance as regression_performance

        return regression_performance(frame, policy)
    if target not in frame or "prediction_probability" not in frame or not len(frame):
        return {"status": "unavailable", "reason": "predictions or labels unavailable"}
    labels = frame[target]
    probabilities = pd.to_numeric(frame.prediction_probability, errors="coerce")
    valid = labels.isin([0, 1]) & probabilities.between(0, 1)
    count = int(valid.sum())
    coverage = count / len(frame)
    if count < policy.minimum_labels or coverage < policy.minimum_label_coverage:
        return {"status": "insufficient", "labeled": count, "coverage": coverage}
    truth, prediction = labels[valid].astype(int), (probabilities[valid] >= threshold).astype(int)
    if truth.nunique() < 2:
        return {
            "status": "insufficient",
            "reason": "both label classes required",
            "labeled": count,
            "coverage": coverage,
        }
    tn, fp, fn, tp = confusion_matrix(truth, prediction, labels=[0, 1]).ravel()
    return {
        "status": "evaluated",
        "labeled": count,
        "coverage": coverage,
        "f1": float(f1_score(truth, prediction, zero_division=0)),
        "confusion": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
    }


def analyze(
    reference: pd.DataFrame, current: pd.DataFrame, config: ModelConfig, policy: Policy
) -> dict:
    findings = []

    def add(kind, severity, feature, **evidence):
        findings.append(
            {"type": kind, "severity": severity, "feature": feature, "evidence": evidence}
        )

    profiles = {"reference": profile(reference, config), "current": profile(current, config)}
    sufficient = min(len(reference), len(current)) >= policy.minimum_rows
    if not sufficient:
        add(
            "MISSING_DATA",
            "WARNING",
            "dataset",
            reference_rows=len(reference),
            current_rows=len(current),
            minimum=policy.minimum_rows,
        )
    quality_failed = False
    for label, frame in [("reference", reference), ("current", current)]:
        if config.is_regression and len(frame):
            from aegis.data.energy import validate_times

            try:
                validate_times(frame)
            except (DataIntegrityError, ValueError, KeyError, AttributeError, TypeError):
                add(
                    "SCHEMA_CHANGE",
                    "CRITICAL",
                    "forecast_time",
                    dataset=label,
                    reason="Invalid timestamp, issue time, hourly order or calendar features",
                )
                quality_failed = True
        if config.target in frame:
            invalid_labels = frame[config.target].notna() & ~frame[config.target].isin([0, 1])
            if config.is_regression:
                values = pd.to_numeric(frame[config.target], errors="coerce")
                invalid_labels = frame[config.target].notna() & (
                    ~np.isfinite(values) | (values < 0)
                )
            if invalid_labels.any():
                add(
                    "UPSTREAM_DATA_FAILURE",
                    "HIGH",
                    "labels",
                    dataset=label,
                    invalid_labels=int(invalid_labels.sum()),
                )
                quality_failed = True
    drift = {}
    for name in config.features.all:
        if name not in reference or name not in current:
            add(
                "SCHEMA_CHANGE",
                "CRITICAL",
                name,
                missing_from=[
                    label
                    for label, frame in [("reference", reference), ("current", current)]
                    if name not in frame
                ],
            )
            quality_failed = True
            continue
        numeric = name in config.features.numeric
        valid_pair = []
        for label, frame in [("reference", reference), ("current", current)]:
            column = frame[name]
            if len(column) and column.isna().mean() > policy.null_fraction:
                add(
                    "MISSING_DATA",
                    "HIGH",
                    name,
                    dataset=label,
                    fraction=float(column.isna().mean()),
                    threshold=policy.null_fraction,
                )
                quality_failed = True
            valid = column.dropna()
            if numeric:
                converted = pd.to_numeric(valid, errors="coerce")
                invalid = ~np.isfinite(converted)
                if invalid.any() or (len(column) and not pd.api.types.is_numeric_dtype(column)):
                    add(
                        "SCHEMA_CHANGE",
                        "HIGH",
                        name,
                        dataset=label,
                        invalid_numeric=int(invalid.sum()),
                        dtype=str(column.dtype),
                    )
                    quality_failed = True
                valid = converted[~invalid]
                if name in policy.ranges and len(column):
                    low, high = policy.ranges[name]
                    fraction = float((~valid.between(low, high)).sum() / len(column))
                    if fraction > policy.invalid_fraction:
                        add(
                            "OUT_OF_RANGE_FEATURE",
                            "HIGH",
                            name,
                            dataset=label,
                            fraction=fraction,
                            bounds=[low, high],
                            threshold=policy.invalid_fraction,
                        )
                        quality_failed = True
            else:
                allowed = policy.categories.get(name, reference[name].dropna().astype(str).unique())
                unknown = valid[~valid.astype(str).isin(allowed)]
                if len(column) and len(unknown) / len(column) > policy.invalid_fraction:
                    add(
                        "SCHEMA_CHANGE",
                        "HIGH",
                        name,
                        dataset=label,
                        new_categories=sorted(unknown.astype(str).unique()),
                        fraction=len(unknown) / len(column),
                        threshold=policy.invalid_fraction,
                    )
                    quality_failed = True
            valid_pair.append(valid)
        a, b = valid_pair
        if min(len(a), len(b)) < policy.minimum_rows:
            continue
        score = distance(a, b, numeric)
        drift[name] = {"distance": score, "method": "ks_distance" if numeric else "total_variation"}
        if score > policy.drift_distance:
            add(
                "DATA_DRIFT",
                "HIGH" if score > policy.critical_drift_distance else "WARNING",
                name,
                **drift[name],
                threshold=policy.drift_distance,
            )
        if numeric:
            q1, q3 = a.quantile(0.25), a.quantile(0.75)
            low, high = q1 - 3 * (q3 - q1), q3 + 3 * (q3 - q1)
            fraction = float((~b.between(low, high)).mean())
            drift[name]["outlier_fraction"] = fraction
            if fraction > policy.outlier_fraction:
                add(
                    "DATA_DRIFT",
                    "WARNING",
                    name,
                    check="outliers",
                    fraction=fraction,
                    bounds=[float(low), float(high)],
                    threshold=policy.outlier_fraction,
                )
    prediction = {"status": "unavailable"}
    prediction_column = "prediction_kw" if config.is_regression else "prediction_probability"
    if all(prediction_column in frame for frame in [reference, current]):
        a, b = [
            pd.to_numeric(frame[prediction_column], errors="coerce")
            for frame in [reference, current]
        ]
        valid = all(
            (np.isfinite(values) & (values >= 0)).all()
            if config.is_regression
            else values.between(0, 1).all()
            for values in [a, b]
        )
        if not valid:
            add("UPSTREAM_DATA_FAILURE", "HIGH", "predictions", reason="invalid probabilities")
            quality_failed = True
        elif sufficient:
            score = distance(a, b, True)
            prediction = {"status": "evaluated", "distance": score, "method": "ks_distance"}
            if score > policy.drift_distance:
                add(
                    "PREDICTION_DRIFT",
                    "WARNING",
                    "predictions",
                    **prediction,
                    threshold=policy.drift_distance,
                )
    metrics = {
        label: performance(frame, config.target, config.training.threshold, policy)
        for label, frame in [("reference", reference), ("current", current)]
    }
    if all(value["status"] == "evaluated" for value in metrics.values()):
        metric = "mape_percent" if config.is_regression else "f1"
        drop = (
            metrics["current"][metric] - metrics["reference"][metric]
            if config.is_regression
            else metrics["reference"][metric] - metrics["current"][metric]
        )
        threshold = policy.mape_increase_points if config.is_regression else policy.f1_drop
        if drop > threshold:
            add(
                "PERFORMANCE_DEGRADATION",
                "HIGH",
                metric,
                drop=drop,
                threshold=threshold,
                reference=metrics["reference"],
                current=metrics["current"],
            )
    if quality_failed:
        add(
            "UPSTREAM_DATA_FAILURE",
            "CRITICAL",
            "dataset",
            reason="Data contract failures; investigate sensor/source before model changes",
        )
    incomplete = (
        not sufficient
        or prediction["status"] != "evaluated"
        or any(metric["status"] != "evaluated" for metric in metrics.values())
    )
    severity = highest(
        [f["severity"] for f in findings] or [Severity.INFO if incomplete else Severity.HEALTHY]
    )
    return {
        "engine_version": "1",
        "severity": str(severity),
        "profiles": profiles,
        "feature_drift": drift,
        "prediction_drift": prediction,
        "performance": metrics,
        "findings": findings,
        "policy": policy.model_dump(mode="json"),
        "policy_hash": digest(canonical(policy.model_dump(mode="json"))),
        "reference_hash": frame_hash(reference),
        "current_hash": frame_hash(current),
        "retraining_allowed": bool(not quality_failed and not incomplete),
        "recommendation": "INVESTIGATE_UPSTREAM"
        if quality_failed
        else "COLLECT_EVIDENCE"
        if incomplete
        else "REVIEW_MODEL"
        if findings
        else "MONITOR",
    }
