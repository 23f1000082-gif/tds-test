
import csv
import math
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(title="eShopCo Telemetry API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["*"],
)

DATA_FILE = Path(__file__).parent / "telemetry.csv"


def load_records():
    if not DATA_FILE.exists():
        raise RuntimeError(
            f"Telemetry dataset not found: {DATA_FILE}"
        )

    with DATA_FILE.open("r", newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def get_value(record, possible_names):
    """Find a column without depending on capitalization."""
    normalized = {
        str(key).strip().lower(): value
        for key, value in record.items()
    }

    for name in possible_names:
        if name.lower() in normalized:
            return normalized[name.lower()]

    raise KeyError(
        f"Missing expected column. Tried: {possible_names}"
    )


def percentile(values, p):
    """Linearly interpolated percentile."""
    values = sorted(values)

    if not values:
        return None

    position = (len(values) - 1) * p
    lower = math.floor(position)
    upper = math.ceil(position)

    if lower == upper:
        return values[lower]

    fraction = position - lower
    return (
        values[lower] * (1 - fraction)
        + values[upper] * fraction
    )


class MetricsRequest(BaseModel):
    regions: list[str]
    threshold_ms: float = 180


@app.get("/")
def health():
    return {"status": "ok"}


@app.post("/api")
def calculate_metrics(body: MetricsRequest):
    try:
        records = load_records()
        response = {}

        for region in body.regions:
            matching = [
                row for row in records
                if str(
                    get_value(row, ["region", "store_region"])
                ).strip().lower() == region.strip().lower()
            ]

            if not matching:
                raise HTTPException(
                    status_code=400,
                    detail=f"No telemetry records for region: {region}"
                )

            latencies = [
                float(get_value(
                    row,
                    ["latency_ms", "latency", "response_time_ms"]
                ))
                for row in matching
            ]

            uptimes = [
                float(get_value(
                    row,
                    ["uptime", "uptime_pct", "uptime_percent"]
                ))
                for row in matching
            ]

            response[region] = {
                "avg_latency": sum(latencies) / len(latencies),
                "p95_latency": percentile(latencies, 0.95),
                "avg_uptime": sum(uptimes) / len(uptimes),
                "breaches": sum(
                    latency > body.threshold_ms
                    for latency in latencies
                ),
            }

        return response

    except HTTPException:
        raise
    except (KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Could not process telemetry data: {exc}"
        )
