"""Throwaway spike: hit Open-Meteo for Brussels and dump the raw response.

Not part of the app - just to see real field names/shapes before writing
SQLAlchemy models. Delete once the schema is settled.
"""

import json
import urllib.parse
import urllib.request

BRUSSELS = {"latitude": 50.8503, "longitude": 4.3517}

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

params = {
    "latitude": BRUSSELS["latitude"],
    "longitude": BRUSSELS["longitude"],
    "hourly": ",".join(HOURLY_VARS),
    "models": "best_match",
    "forecast_days": 7,
    "timezone": "UTC",
}

url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params)
print(f"GET {url}\n")

with urllib.request.urlopen(url) as response:
    data = json.load(response)

print(json.dumps(data, indent=2))

temps = data["hourly"]["temperature_2m"]
times = data["hourly"]["time"]

print("\n---")
print(type(temps), len(temps))
for t, v in zip(times[:5], temps[:5]):
    print(t, v)

