"""Send actual HTTP traffic and optional delayed synthetic ground-truth labels."""

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import numpy as np

from aegis.core.config import Settings, load_config
from aegis.data.fraud import load_dataset, setup_dataset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--count", type=int, default=200)
    parser.add_argument("--rate", type=float, default=10)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--labels", action="store_true")
    parser.add_argument("--invalid-every", type=int, default=0)
    args = parser.parse_args()
    if not (
        1 <= args.count <= 100000
        and 0 < args.rate <= 1000
        and 1 <= args.concurrency <= 32
        and args.invalid_every >= 0
    ):
        parser.error("Invalid count, rate, concurrency or validation-error interval")
    config = load_config(Path("configs/models/fraud.yaml"))
    path = setup_dataset(config.dataset, Settings().data_root)
    _, frames = load_dataset(path)
    rows = frames["test"].sample(frac=1, random_state=42).to_dict(orient="records")
    durations, events, statuses = [], [], {}
    with httpx.Client(base_url=args.url, timeout=15, trust_env=False) as client:
        client.get("/health/ready").raise_for_status()

        def predict(index):
            row = rows[index % len(rows)]
            payload = {key: row[key] for key in config.features.all}
            if args.invalid_every and (index + 1) % args.invalid_every == 0:
                payload["hour"] = 99
            started = time.perf_counter()
            result = client.post("/api/v1/predict", json=payload)
            return result, time.perf_counter() - started, row[config.target]

        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            futures = []
            for index in range(args.count):
                due = started + index / args.rate
                time.sleep(max(0, due - time.perf_counter()))
                futures.append(pool.submit(predict, index))
            for future in futures:
                result, elapsed, label = future.result()
                durations.append(elapsed * 1000)
                statuses[result.status_code] = statuses.get(result.status_code, 0) + 1
                if result.status_code == 200:
                    events.append((result.json()["prediction_id"], label))
        # Labels arrive after the inference batch, never as prediction inputs.
        if args.labels:
            for event_id, label in events:
                client.put(
                    f"/api/v1/predictions/{event_id}/label", json={"actual_label": int(label)}
                ).raise_for_status()
        summary = client.get("/api/v1/monitoring/summary")
        summary.raise_for_status()
        print(
            json.dumps(
                {
                    "requests": args.count,
                    "statuses": statuses,
                    "labeled": len(events) if args.labels else 0,
                    "client_latency_ms": dict(
                        zip(
                            ["p50", "p95", "p99"],
                            np.percentile(durations, [50, 95, 99]).tolist(),
                            strict=True,
                        )
                    ),
                    "model_summary": summary.json(),
                },
                indent=2,
            )
        )
        if any(code >= 500 for code in statuses):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
