"""One-shot initial ingestion so a fresh `docker compose up` has real
forecast data to look at immediately, not just an empty dashboard.

Deliberately best-effort, unlike migration/seeding: this depends on a
third-party API (Open-Meteo) being reachable, which migrations and location
seeding don't. A failure here must not block the stack from starting - the
frontend already treats "no forecast data yet" as a normal, non-error
state. The `migrate` service's command wraps this call with `|| true` so a
failure here can't fail the exit code `backend` depends on.
"""

from app.db import SessionLocal
from app.ingestion import fetch_forecast, run_ingestion_cycle
from app.models import Location


def main() -> None:
    with SessionLocal() as session:
        location_ids = [loc.id for loc in session.query(Location).all()]

    results = run_ingestion_cycle(SessionLocal, location_ids, fetch=fetch_forecast)
    for result in results:
        print(result)


if __name__ == "__main__":
    main()
