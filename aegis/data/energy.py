"""Hourly synthetic energy demand; predictors available one hour before target time."""

import json
import shutil
import tempfile

import numpy as np
import pandas as pd

from aegis.core.errors import DataIntegrityError
from aegis.data.fraud import SPLITS, canonical, digest, load_dataset


def generate(config):
    rng = np.random.default_rng(config.seed)
    n = config.samples + 24
    time = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    hour = time.hour.to_numpy()
    weekday = time.dayofweek.to_numpy()
    temperature = 20 + 8 * np.sin(2 * np.pi * (hour - 8) / 24) + rng.normal(0, 2, n)
    occupancy = np.clip(
        20 + 65 * ((hour >= 8) & (hour <= 18) & (weekday < 5)) + rng.normal(0, 7, n), 0, 100
    )
    demand = 40 + 1.2 * occupancy + 0.7 * np.abs(temperature - 20) + rng.normal(0, 3, n)
    frame = pd.DataFrame(
        {
            "timestamp": time.astype(str),
            "issued_at": (time - pd.Timedelta(hours=1)).astype(str),
            "hour": hour,
            "day_of_week": weekday,
            "forecast_temperature": temperature.round(4),
            "forecast_occupancy": occupancy.round(4),
            "lag_24h_kw": pd.Series(demand).shift(24).round(4),
            "demand_kw": demand.round(4),
        }
    )
    return frame.iloc[24:].reset_index(drop=True)


def validate_times(frame):
    times = pd.to_datetime(frame.timestamp, utc=True, errors="raise")
    issued = pd.to_datetime(frame.issued_at, utc=True, errors="raise")
    if (
        frame.empty
        or times.isna().any()
        or not times.is_unique
        or not times.is_monotonic_increasing
        or not ((times - issued) == pd.Timedelta(hours=1)).all()
    ):
        raise DataIntegrityError("Energy readings require unique ordered hourly forecast times")
    if len(times) > 1 and not times.diff().iloc[1:].eq(pd.Timedelta(hours=1)).all():
        raise DataIntegrityError("Energy times must be contiguous hourly observations")
    if (
        not (frame.hour == times.dt.hour).all()
        or not (frame.day_of_week == times.dt.dayofweek).all()
    ):
        raise DataIntegrityError("Calendar features must match the forecast target timestamp")
    return times


def validate_split(frame, previous):
    times = validate_times(frame)
    for prior in previous.values():
        if pd.to_datetime(prior.timestamp, utc=True).max() >= times.min():
            raise DataIntegrityError("Energy splits must be chronological and disjoint")
    values = frame[["demand_kw", "lag_24h_kw"]].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values < 0).any():
        raise DataIntegrityError("Energy targets and known lags must be finite and nonnegative")


def setup_dataset(config, root):
    root = root.resolve() / config.name
    root.mkdir(parents=True, exist_ok=True)
    frame = generate(config)
    train_end = int(len(frame) * (1 - config.validation_fraction - config.test_fraction))
    validation_end = len(frame) - int(len(frame) * config.test_fraction)
    splits = [
        frame.iloc[:train_end],
        frame.iloc[train_end:validation_end],
        frame.iloc[validation_end:],
    ]
    with tempfile.TemporaryDirectory(prefix=".building-", dir=root) as temporary:
        from pathlib import Path

        staging = Path(temporary)
        manifest = {
            "source": "AegisML synthetic hourly energy v1; not real utility data",
            "generator": config.model_dump(),
            "split_method": "chronological",
            "forecast_horizon_hours": 1,
            "lag_hours": 24,
            "splits": {},
        }
        for name, split in zip(SPLITS, splits, strict=True):
            path = staging / f"{name}.csv"
            split.to_csv(path, index=False, lineterminator="\n")
            manifest["splits"][name] = {"sha256": digest(path.read_bytes()), "rows": len(split)}
        fingerprint = digest(canonical(manifest))
        manifest["fingerprint"] = fingerprint
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        destination = root / fingerprint
        if not destination.exists():
            shutil.copytree(staging, destination)
        load_dataset(destination)
    return destination


def inject(frame, scenario):
    result = frame.copy(deep=True)
    afternoon = result.hour.between(14, 18)
    if scenario == "occupancy-shift":
        old = result.forecast_occupancy.copy()
        result.loc[afternoon, "forecast_occupancy"] = 160.0
        result.loc[afternoon, "demand_kw"] += 1.6 * (160 - old[afternoon])
    elif scenario == "upstream-corruption":
        result.loc[afternoon, "forecast_occupancy"] = -999.0
        result.loc[afternoon, "forecast_temperature"] = np.nan
    elif scenario == "model-degradation":
        result.loc[afternoon, "demand_kw"] *= 1.8
    elif scenario != "healthy":
        raise ValueError(f"Unknown energy scenario: {scenario}")
    return result
