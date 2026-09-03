import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Location(Base):
    """Fixed, seeded set of Belgian cities. See PLAN.md."""

    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    slug: Mapped[str] = mapped_column(unique=True, index=True)
    name: Mapped[str]
    latitude: Mapped[float] = mapped_column(Numeric)
    longitude: Mapped[float] = mapped_column(Numeric)
    timezone: Mapped[str]

    ingestion_runs: Mapped[list["IngestionRun"]] = relationship(
        back_populates="location"
    )
    forecast_values: Mapped[list["ForecastValue"]] = relationship(
        back_populates="location"
    )


class IngestionRun(Base):
    """Operational log of one poll attempt for one location.

    `scheduled_for` is the deterministic poll slot (floor(now_utc, 6h)),
    computed once per poll cycle and shared by every location polled in
    that cycle. It is copied into every ForecastValue.issued_at that this
    run writes, which is what makes retries idempotent: a retried run
    recomputes the same scheduled_for, so its inserts collide harmlessly
    with rows already written instead of duplicating them. `started_at` is
    wall-clock and only for observability — never used as a data key.
    """

    __tablename__ = "ingestion_runs"
    __table_args__ = (
        CheckConstraint(
            "status in ('running', 'success', 'failed')", name="ck_ingestion_runs_status"
        ),
        Index("ix_ingestion_runs_location_scheduled_for", "location_id", "scheduled_for"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    scheduled_for: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True)
    )
    started_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True)
    )
    finished_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    status: Mapped[str] = mapped_column(default="running")
    rows_inserted: Mapped[int | None]
    error_message: Mapped[str | None]

    location: Mapped["Location"] = relationship(back_populates="ingestion_runs")
    forecast_values: Mapped[list["ForecastValue"]] = relationship(
        back_populates="ingestion_run"
    )


class ForecastValue(Base):
    """One row per poll per (location, target_hour) — see PLAN.md.

    issued_at is copied from the owning IngestionRun.scheduled_for, never
    set independently per row. UNIQUE(location_id, target_time, issued_at)
    is both the natural key and the idempotency key: ingestion inserts with
    ON CONFLICT ... DO NOTHING against it.
    """

    __tablename__ = "forecast_values"
    __table_args__ = (
        UniqueConstraint(
            "location_id", "target_time", "issued_at", name="uq_forecast_values_natural_key"
        ),
        Index(
            "ix_forecast_values_location_target_issued",
            "location_id",
            "target_time",
            "issued_at",
        ),
        Index("ix_forecast_values_issued_at", "issued_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    target_time: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True)
    )
    issued_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True)
    )
    ingestion_run_id: Mapped[int] = mapped_column(ForeignKey("ingestion_runs.id"))

    temperature_c: Mapped[float | None] = mapped_column(Numeric)
    precipitation_mm: Mapped[float | None] = mapped_column(Numeric)
    precipitation_probability: Mapped[int | None] = mapped_column(SmallInteger)
    wind_speed_kmh: Mapped[float | None] = mapped_column(Numeric)
    wind_direction_deg: Mapped[int | None] = mapped_column(SmallInteger)
    cloud_cover_pct: Mapped[int | None] = mapped_column(SmallInteger)
    relative_humidity_pct: Mapped[int | None] = mapped_column(SmallInteger)
    weather_code: Mapped[int | None] = mapped_column(SmallInteger)

    location: Mapped["Location"] = relationship(back_populates="forecast_values")
    ingestion_run: Mapped["IngestionRun"] = relationship(back_populates="forecast_values")
