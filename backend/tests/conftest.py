"""Test infra: a real, throwaway Postgres container for the whole test
session (spinning one up per test would be slow), with tables recreated
per test for isolation. This exercises the actual ON CONFLICT / transaction
behavior of Postgres - not sqlite, which doesn't share those semantics.
"""

import subprocess
import time
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base


@pytest.fixture(scope="session")
def postgres_url():
    container_name = f"ella-weather-test-pg-{uuid.uuid4().hex[:8]}"
    port = 55433
    subprocess.run(
        [
            "docker", "run", "-d", "--name", container_name,
            "-e", "POSTGRES_PASSWORD=postgres",
            "-e", "POSTGRES_DB=ella_weather_test",
            "-p", f"{port}:5432",
            "postgres:16-alpine",
        ],
        check=True,
        capture_output=True,
    )
    try:
        _wait_until_ready(container_name)
        yield f"postgresql+psycopg://postgres:postgres@localhost:{port}/ella_weather_test"
    finally:
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)


def _wait_until_ready(container_name: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["docker", "exec", container_name, "pg_isready", "-U", "postgres"],
            capture_output=True,
        )
        if result.returncode == 0:
            return
        time.sleep(0.5)
    raise TimeoutError(f"Postgres in {container_name} did not become ready in time")


@pytest.fixture()
def session_factory(postgres_url):
    engine = create_engine(postgres_url)
    Base.metadata.create_all(engine)
    try:
        yield sessionmaker(bind=engine)
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
