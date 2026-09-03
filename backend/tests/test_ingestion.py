"""Tests exercise the real ingest_location/run_ingestion_cycle code path
against a real Postgres - only the network call (`fetch`) is faked, since
that's the actual I/O boundary of the system under test.
"""

import datetime as dt

from app.ingestion import run_ingestion_cycle
from app.models import ForecastValue, IngestionRun, Location

FIXED_NOW = dt.datetime(2026, 9, 3, 6, 2, tzinfo=dt.timezone.utc)  # floors to 06:00 UTC

SAMPLE_PAYLOAD = {
    "hourly": {
        "time": ["2026-09-03T00:00", "2026-09-03T01:00", "2026-09-03T02:00"],
        "temperature_2m": [10.0, 10.5, 11.0],
        "precipitation": [0.0, 0.1, 0.0],
        "precipitation_probability": [10, 20, 30],
        "wind_speed_10m": [5.0, 6.0, 7.0],
        "wind_direction_10m": [180, 190, 200],
        "cloud_cover": [50, 60, 70],
        "relative_humidity_2m": [80, 81, 82],
        "weather_code": [1, 2, 3],
    }
}


def fake_fetch(location):
    return SAMPLE_PAYLOAD


def seed_location(session_factory, slug: str) -> int:
    with session_factory() as session:
        location = Location(
            slug=slug,
            name=slug.title(),
            latitude=50.85,
            longitude=4.35,
            timezone="Europe/Brussels",
        )
        session.add(location)
        session.commit()
        return location.id


def test_retry_with_same_scheduled_for_inserts_zero_new_rows(session_factory):
    location_id = seed_location(session_factory, "brussels")

    run_ingestion_cycle(session_factory, [location_id], now=FIXED_NOW, fetch=fake_fetch)

    with session_factory() as session:
        assert session.query(ForecastValue).count() == 3
        first_run = session.query(IngestionRun).one()
        assert first_run.rows_inserted == 3

    # Retry: same location, same `now` -> floor_to_cadence recomputes the
    # identical scheduled_for. Goes through run_ingestion_cycle for real -
    # no hand-crafted SQL.
    run_ingestion_cycle(session_factory, [location_id], now=FIXED_NOW, fetch=fake_fetch)

    with session_factory() as session:
        total_rows = session.query(ForecastValue).count()
        runs = session.query(IngestionRun).order_by(IngestionRun.id).all()

    assert total_rows == 3, "retry must insert zero NEW rows"
    assert len(runs) == 2, "retry still logs its own ingestion_runs row"
    assert runs[0].rows_inserted == 3
    assert runs[1].rows_inserted == 0, "everything on retry collided via ON CONFLICT DO NOTHING"
    assert runs[0].scheduled_for == runs[1].scheduled_for


def test_crash_on_third_location_leaves_first_two_committed_and_logs_the_failure(session_factory):
    """A location that errors doesn't abort the cycle (the other locations
    still get processed) and doesn't vanish silently either - it leaves
    exactly one IngestionRun row recording the failure, with no partial
    ForecastValue rows for that location.
    """
    ids = [seed_location(session_factory, slug) for slug in ("brussels", "antwerp", "ghent")]

    call_count = {"n": 0}

    def fetch_that_crashes_on_third_location(location):
        call_count["n"] += 1
        if call_count["n"] == 3:
            raise RuntimeError("simulated crash mid-run")
        return SAMPLE_PAYLOAD

    # No longer raises out of run_ingestion_cycle - the failure is caught,
    # logged, and the cycle completes.
    results = run_ingestion_cycle(
        session_factory, ids, now=FIXED_NOW, fetch=fetch_that_crashes_on_third_location
    )
    assert [r["status"] for r in results] == ["success", "success", "failed"]

    with session_factory() as session:
        all_runs = session.query(IngestionRun).all()
        forecast_counts = {
            loc_id: session.query(ForecastValue).filter_by(location_id=loc_id).count()
            for loc_id in ids
        }

    runs_by_location: dict[int, IngestionRun] = {}
    for run in all_runs:
        assert run.location_id not in runs_by_location, "duplicate IngestionRun row for a location"
        runs_by_location[run.location_id] = run

    # First two locations: fully committed, complete data, successful runs.
    assert runs_by_location[ids[0]].status == "success"
    assert runs_by_location[ids[0]].rows_inserted == 3
    assert forecast_counts[ids[0]] == 3

    assert runs_by_location[ids[1]].status == "success"
    assert runs_by_location[ids[1]].rows_inserted == 3
    assert forecast_counts[ids[1]] == 3

    # Third location: exactly one IngestionRun row, status='failed', with
    # the error recorded - and zero ForecastValue rows (the partial
    # 'running' attempt was rolled back, not left half-inserted).
    assert len(runs_by_location) == 3
    failed_run = runs_by_location[ids[2]]
    assert failed_run.status == "failed"
    assert failed_run.rows_inserted == 0
    assert "simulated crash mid-run" in failed_run.error_message
    assert forecast_counts[ids[2]] == 0

    # Exactly one IngestionRun row overall for the failed location - not
    # zero (invisible failure) and not more than one (duplicate logging).
    # The duplicate-detecting loop above already enforces "at most one";
    # this confirms "at least one" (i.e. it isn't silently missing).
    assert ids[2] in runs_by_location
