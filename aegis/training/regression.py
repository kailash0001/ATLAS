import numpy as np


def metrics(truth, prediction):
    truth, prediction = np.asarray(truth, dtype=float), np.asarray(prediction, dtype=float)
    if not len(truth) or not np.isfinite(truth).all() or not np.isfinite(prediction).all():
        raise ValueError("Regression metrics require finite nonempty aligned values")
    if truth.shape != prediction.shape:
        raise ValueError("Regression truth and predictions must align")
    error = prediction - truth
    nonzero = np.abs(truth) > 1e-6
    result = {
        "mae": float(np.abs(error).mean()),
        "rmse": float(np.sqrt((error**2).mean())),
        "mape_coverage": float(nonzero.mean()),
    }
    if nonzero.any():
        result["mape_percent"] = float((np.abs(error[nonzero] / truth[nonzero])).mean() * 100)
    return result
