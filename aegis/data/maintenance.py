"""Reproducible synthetic equipment readings and explicit, opt-in faults."""

import numpy as np
import pandas as pd

from aegis.core.config import DatasetConfig


def generate(config: DatasetConfig) -> pd.DataFrame:
    rng = np.random.default_rng(config.seed)
    n = config.samples
    wear = rng.beta(2, 3, n)
    frame = pd.DataFrame(
        {
            "temperature": rng.normal(65, 6, n) + 28 * wear,
            "vibration": rng.normal(1.5, 0.25, n) + 5 * wear,
            "pressure": rng.normal(100, 8, n) - 15 * wear,
            "rpm": rng.normal(1500, 100, n),
            "voltage": rng.normal(230, 4, n),
            "current": rng.normal(10, 1, n) + 4 * wear,
            "operating_hours": (wear * 30000).round(),
            "machine_type": rng.choice(["pump", "compressor", "motor"], n),
        }
    )
    risk = -6 + 7 * wear + 0.16 * (frame.temperature - 75) + 0.8 * (frame.vibration - 3)
    frame["failure"] = rng.binomial(1, 1 / (1 + np.exp(-risk)))
    frame.insert(0, "reading_id", [f"sensor-{config.seed}-{i:08d}" for i in range(n)])
    return frame.round(4)


def inject(frame: pd.DataFrame, scenario: str, seed: int = 42) -> pd.DataFrame:
    """Modify copied readings, retaining real labels; never change training artifacts."""
    result = frame.copy(deep=True)
    rng = np.random.default_rng(seed)
    rows = rng.choice(result.index, max(1, len(result) // 3), replace=False)
    if scenario == "sensor-corruption":
        result.loc[rows, "temperature"] = 999.0
        result.loc[rows, "voltage"] = np.nan
        result.loc[rows, "vibration"] = -10.0
    elif scenario == "drift":
        result["temperature"] += 12
        result["vibration"] += 1.5
    elif scenario == "new-category":
        result.loc[rows, "machine_type"] = "unknown-device"
    elif scenario == "schema":
        result = result.drop(columns="pressure")
    elif scenario == "performance":
        # Explicit synthetic concept shift: invert observed failure outcomes.
        result["failure"] = 1 - result["failure"]
    elif scenario != "healthy":
        raise ValueError(f"Unknown fault scenario: {scenario}")
    return result
