"""Optional OSS visual supplement; Aegis policies remain authoritative."""

import os
from importlib.metadata import version

from aegis.core.errors import AegisError


def export(reference, current, config, path):
    os.environ.setdefault("DO_NOT_TRACK", "1")
    os.environ.setdefault("EVIDENTLY_DISABLE_TELEMETRY", "1")
    try:
        from evidently import Report
        from evidently.presets import DataDriftPreset
    except ImportError as exc:
        raise AegisError("Install the reliability extra to export Evidently reports") from exc
    columns = [
        column
        for column in config.features.all
        if column in reference
        and column in current
        and reference[column].notna().any()
        and current[column].notna().any()
    ]
    if not columns or min(len(reference), len(current)) < 2:
        raise AegisError("Evidently export requires shared nonempty feature columns")
    snapshot = Report([DataDriftPreset()]).run(
        reference_data=reference[columns], current_data=current[columns]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    snapshot.save_html(str(path))
    return {
        "version": version("evidently"),
        "html": str(path.resolve()),
        "role": "supplemental; independent thresholds are not Aegis policies",
    }
