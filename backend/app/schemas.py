import datetime

from pydantic import BaseModel, ConfigDict


class LocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str
    latitude: float
    longitude: float
    timezone: str


class ForecastValueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    target_time: datetime.datetime
    issued_at: datetime.datetime
    temperature_c: float | None
    precipitation_mm: float | None
    precipitation_probability: int | None
    wind_speed_kmh: float | None
    wind_direction_deg: int | None
    cloud_cover_pct: int | None
    relative_humidity_pct: int | None
    weather_code: int | None
