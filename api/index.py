
import json
import math
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="eShopCo Telemetry API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["*"],
)

DATA_FILE = Path(__file__).parent / "q-vercel-latency.json"


def load_records():
    with DATA_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in ("records", "data", "telemetry", "pings"):
            if isinstance(data.get(key), list):
                return data[key]

    raise ValueError("Unexpected JSON dataset structure")


def get_value(record, names):
    normalized = {
        str(k).strip().lower(): v
        for k, v in record.items()
    }

    for name in names:
        if name.lower() in normalized:
            return normalized[name.lower()]

    raise KeyError(f"Missing field; tried {names}")


def percentile(values, p):
    values = sorted(values)
    if not values:
        return None

    pos = (len(values) - 1) * p
    lo = math.floor(pos)
    hi = math.ceil(pos)

    if lo == hi:
        return values[lo]

    return values[lo] * (hi - pos) + values[hi] * (pos - lo)


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
        result = {}

        for region in body.regions:
            rows = [
                r for r in records
                if str(get_value(r, ["region", "store_region"]))
                .strip().lower() == region.strip().lower()
            ]

            if not rows:
                raise HTTPException(
                    status_code=400,
                    detail=f"No records for region {region}"
                )

            latencies = [
                float(get_value(
                    r, ["latency_ms", "latency", "response_time_ms"]
                ))
                for r in rows
            ]

            uptimes = [
                float(get_value(
                    r, ["uptime", "avg_uptime", "uptime_pct",
                        "uptime_percent"]
                ))
                for r in rows
            ]

            result[region] = {
                "avg_latency": sum(latencies) / len(latencies),
                "p95_latency": percentile(latencies, 0.95),
                "avg_uptime": sum(uptimes) / len(uptimes),
                "breaches": sum(
                    x > body.threshold_ms for x in latencies
                ),
            }

        return result

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
