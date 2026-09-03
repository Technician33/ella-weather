"""Ingestion job: poll Open-Meteo and write forecast revisions.

See PLAN.md for the design rationale. The key invariant: `scheduled_for` is
computed exactly once per poll cycle and threaded unchanged into every row
written during that cycle, which is what makes retries idempotent via
ON CONFLICT DO NOTHING on (location_id, target_time, issued_at).

Each location is ingested in its own Session (= its own transaction). Nothing
for a location - not even its IngestionRun row - is committed until that
location's work is entirely done. If anything raises first, exiting the
`with` block closes (and thereby rolls back) that session, so the location
is left exactly as if it had never been attempted.
"""

from __future__ import annotations

import datetime as dt
import json
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, sessionmaker

from app.models import ForecastValue, IngestionRun, Location

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
POLL_CADENCE_HOURS = 6

HOURLY_VARS = [
    "temperature_2m",
    "precipitation",
    "precipitation_probability",
    "wind_speed_10m",
    "wind_direction_10m",
    "cloud_cover",
    "relative_humidity_2m",
    "weather_code",
]

VARIABLE_TO_COLUMN = {
    "temperature_2m": "temperature_c",
    "precipitation": "precipitation_mm",
    "precipitation_probability": "precipitation_probability",
    "wind_speed_10m": "wind_speed_kmh",
    "wind_direction_10m": "wind_direction_deg",
    "cloud_cover": "cloud_cover_pct",
    "relative_humidity_2m": "relative_humidity_pct",
    "weather_code": "weather_code",
}


def floor_to_cadence(moment: dt.datetime, cadence_hours: int = POLL_CADENCE_HOURS) -> dt.datetime:
    """Round a UTC-aware timestamp down to the nearest cadence boundary.

    The same wall-clock moment, floored any number of times within the same
    cadence window, always yields the identical timestamp - that's the
    entire idempotency mechanism.
    """
    if moment.tzinfo is None:
        raise ValueError("moment must be timezone-aware")
    moment = moment.astimezone(dt.timezone.utc)
    floored_hour = (moment.hour // cadence_hours) * cadence_hours
    return moment.replace(hour=floored_hour, minute=0, second=0, microsecond=0)


def fetch_forecast(location: Location) -> dict:
    """Call Open-Meteo for one location. Real network I/O - replaced by a
    fake in tests so tests exercise ingest_location's logic, not the network.
    """
    params = {
        "latitude": float(location.latitude),
        "longitude": float(location.longitude),
        "hourly": ",".join(HOURLY_VARS),
        "models": "best_match",
        "forecast_days": 7,
        "timezone": "UTC",
    }
    url = OPEN_METEO_URL + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.load(response)


def build_forecast_rows(
    location_id: int,
    ingestion_run_id: int,
    issued_at: dt.datetime,
    payload: dict,
) -> list[dict]:
    hourly = payload["hourly"]
    times = hourly["time"]
    rows = []
    for i, time_str in enumerate(times):
        target_time = dt.datetime.fromisoformat(time_str).replace(tzinfo=dt.timezone.utc)
        row = {
            "location_id": location_id,
            "target_time": target_time,
            "issued_at": issued_at,
            "ingestion_run_id": ingestion_run_id,
        }
        for source_key, column in VARIABLE_TO_COLUMN.items():
            row[column] = hourly[source_key][i]
        rows.append(row)
    return rows


def ingest_location(
    session: Session,
    location_id: int,
    scheduled_for: dt.datetime,
    fetch: Callable[[Location], dict] = fetch_forecast,
) -> dict:
    """Ingest one location's forecast.

    On success: one IngestionRun row (status='success') and that location's
    ForecastValue rows are committed together as a single unit.

    On failure: the partial attempt (the 'running' IngestionRun row and any
    forecast rows inserted before the failure) is rolled back entirely -
    Postgres discards it as if it never happened - and a *separate*,
    freshly committed IngestionRun row with status='failed' and
    error_message records the failure on its own, so it isn't invisible in
    the database. The caller moves on to the next location rather than
    aborting the whole cycle.
    """
    location = session.get(Location, location_id)
    started_at = dt.datetime.now(dt.timezone.utc)

    try:
        run = IngestionRun(
            location_id=location.id,
            scheduled_for=scheduled_for,
            started_at=started_at,
            status="running",
        )
        session.add(run)
        session.flush()  # assigns run.id without ending the transaction

        payload = fetch(location)
        rows = build_forecast_rows(location.id, run.id, scheduled_for, payload)

        inserted = 0
        if rows:
            # cursor.rowcount is unreliable for a multi-row INSERT sent as an
            # executemany-style batch, so count RETURNING rows instead: rows
            # skipped by DO NOTHING produce no output row at all.
            stmt = (
                pg_insert(ForecastValue.__table__)
                .values(rows)
                .on_conflict_do_nothing(
                    index_elements=["location_id", "target_time", "issued_at"]
                )
                .returning(ForecastValue.__table__.c.id)
            )
            result = session.execute(stmt)
            inserted = len(result.fetchall())

        run.status = "success"
        run.rows_inserted = inserted
        run.finished_at = dt.datetime.now(dt.timezone.utc)
        session.commit()

        return {
            "location_id": location_id,
            "status": "success",
            "rows_inserted": inserted,
            "error": None,
        }

    except Exception as exc:
        session.rollback()  # discards the pending 'running' row and any partial inserts

        failed_run = IngestionRun(
            location_id=location_id,
            scheduled_for=scheduled_for,
            started_at=started_at,
            finished_at=dt.datetime.now(dt.timezone.utc),
            status="failed",
            rows_inserted=0,
            error_message=str(exc),
        )
        session.add(failed_run)
        session.commit()

        return {
            "location_id": location_id,
            "status": "failed",
            "rows_inserted": 0,
            "error": str(exc),
        }


def run_ingestion_cycle(
    session_factory: sessionmaker,
    location_ids: Sequence[int],
    now: dt.datetime | None = None,
    fetch: Callable[[Location], dict] = fetch_forecast,
) -> list[dict]:
    """One poll cycle across all locations.

    scheduled_for is computed exactly once here, before any location is
    touched, and passed down unchanged - the single source of truth for
    the idempotency guarantee described in PLAN.md. A single location
    failing does not stop the others: ingest_location catches its own
    errors and always returns a result, so this always processes every
    location and returns one result dict per location.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    scheduled_for = floor_to_cadence(now)

    results = []
    for location_id in location_ids:
        with session_factory() as session:
            results.append(ingest_location(session, location_id, scheduled_for, fetch=fetch))

    return results
