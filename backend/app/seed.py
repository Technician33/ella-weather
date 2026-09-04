"""Seed the fixed set of locations from PLAN.md. Idempotent - safe to run
on every `docker compose up`, including against a database that already
has these rows from a previous run.
"""

from app.db import SessionLocal
from app.models import Location

CITIES = [
    ("brussels", "Brussels", 50.8503, 4.3517),
    ("antwerp", "Antwerp", 51.2194, 4.4025),
    ("ghent", "Ghent", 51.0543, 3.7174),
    ("liege", "Liège", 50.6326, 5.5797),
    ("bruges", "Bruges", 51.2093, 3.2247),
]


def seed() -> None:
    with SessionLocal() as session:
        for slug, name, latitude, longitude in CITIES:
            if session.query(Location).filter_by(slug=slug).first():
                continue
            session.add(
                Location(
                    slug=slug,
                    name=name,
                    latitude=latitude,
                    longitude=longitude,
                    timezone="Europe/Brussels",
                )
            )
        session.commit()


if __name__ == "__main__":
    seed()
