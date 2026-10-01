import numpy as np
import pandas as pd

from aegis.training.regression import metrics


def performance(frame, policy):
    if not len(frame) or not {"demand_kw", "prediction_kw"} <= set(frame.columns):
        return {"status": "unavailable", "reason": "predictions or actual demand unavailable"}
    truth = pd.to_numeric(frame.demand_kw, errors="coerce")
    prediction = pd.to_numeric(frame.prediction_kw, errors="coerce")
    valid = np.isfinite(truth) & np.isfinite(prediction) & (truth >= 0) & (prediction >= 0)
    count, coverage = int(valid.sum()), float(valid.mean())
    if count < policy.minimum_labels or coverage < policy.minimum_label_coverage:
        return {"status": "insufficient", "labeled": count, "coverage": coverage}
    result = metrics(truth[valid], prediction[valid])
    # Never report zero-target MAPE as zero or silently ignore most outcomes.
    status = (
        "evaluated" if result["mape_coverage"] >= policy.minimum_label_coverage else "insufficient"
    )
    result.update({"status": status, "labeled": count, "coverage": coverage, "by_hour": {}})
    if "hour" in frame:
        for hour in sorted(frame.loc[valid, "hour"].unique()):
            selected = valid & (frame.hour == hour)
            result["by_hour"][str(int(hour))] = {
                "count": int(selected.sum()),
                **metrics(truth[selected], prediction[selected]),
            }
    return result
