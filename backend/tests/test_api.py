"""API tests go through FastAPI's real TestClient against a real Postgres
(the session_factory fixture from conftest.py) - only the DB session
dependency is swapped to point at the throwaway test database, not the
route logic itself.
"""

from fastapi.testclient import TestClient

from app.main import app, get_session
from app.models import Location


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


def make_client(session_factory) -> TestClient:
    def override_get_session():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app)


def test_current_forecast_404s_for_unknown_slug(session_factory):
    client = make_client(session_factory)
    try:
        response = client.get("/locations/nowhereville/forecast/current")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert "nowhereville" in response.json()["detail"]


def test_forecast_history_404s_for_unknown_slug(session_factory):
    client = make_client(session_factory)
    try:
        response = client.get(
            "/locations/nowhereville/forecast/history",
            params={"target_time": "2026-09-04T14:00:00Z"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert "nowhereville" in response.json()["detail"]


def test_forecast_history_returns_empty_list_for_known_location_with_unmatched_target_time(
    session_factory,
):
    """An unknown slug is a 404 (no such resource); an unmatched target_time
    on a real location is not an error - it's a well-formed query that
    legitimately has zero results (e.g. that hour hasn't been polled yet).
    """
    seed_location(session_factory, "brussels")
    client = make_client(session_factory)
    try:
        response = client.get(
            "/locations/brussels/forecast/history",
            params={"target_time": "2099-01-01T00:00:00Z"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == []
