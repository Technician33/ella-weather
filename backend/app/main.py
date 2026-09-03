"""FastAPI service. Only the three endpoints PLAN.md calls out for the
current timebox - /forecast/as-of is explicitly cut, not just unbuilt yet.
"""

import datetime

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import ForecastValue, Location
from app.schemas import ForecastValueOut, LocationOut

app = FastAPI(title="Ella Weather API")


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def get_location_or_404(session: Session, slug: str) -> Location:
    location = session.query(Location).filter_by(slug=slug).first()
    if location is None:
        raise HTTPException(status_code=404, detail=f"No location with slug '{slug}'")
    return location


@app.get("/locations", response_model=list[LocationOut])
def list_locations(session: Session = Depends(get_session)):
    return session.query(Location).order_by(Location.slug).all()


@app.get("/locations/{slug}/forecast/current", response_model=list[ForecastValueOut])
def current_forecast(slug: str, session: Session = Depends(get_session)):
    location = get_location_or_404(session, slug)

    # DISTINCT ON (target_time), keeping the row with the greatest issued_at
    # per target_time - Postgres requires ORDER BY to lead with the same
    # expression(s) passed to DISTINCT ON.
    rows = (
        session.query(ForecastValue)
        .filter(ForecastValue.location_id == location.id)
        .order_by(ForecastValue.target_time, ForecastValue.issued_at.desc())
        .distinct(ForecastValue.target_time)
        .all()
    )
    return rows


@app.get("/locations/{slug}/forecast/history", response_model=list[ForecastValueOut])
def forecast_history(
    slug: str,
    target_time: datetime.datetime = Query(
        ..., description="The forecasted hour to show revision history for, ISO 8601"
    ),
    session: Session = Depends(get_session),
):
    location = get_location_or_404(session, slug)

    if target_time.tzinfo is None:
        target_time = target_time.replace(tzinfo=datetime.timezone.utc)
    else:
        target_time = target_time.astimezone(datetime.timezone.utc)

    # A valid location with no revisions for this hour isn't an error - it's
    # a well-formed query that legitimately has zero results (the hour may
    # not have been polled yet, or falls outside the forecast horizon). Only
    # an unknown location is a 404; an empty result here is 200 + [].
    return (
        session.query(ForecastValue)
        .filter(
            ForecastValue.location_id == location.id,
            ForecastValue.target_time == target_time,
        )
        .order_by(ForecastValue.issued_at)
        .all()
    )
