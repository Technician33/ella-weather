# Ella Weather

Ingests Belgian weather forecasts from Open-Meteo into PostgreSQL, preserving
every forecast revision per target hour — a forecast issued today for
tomorrow 2pm never overwrites yesterday's forecast for that same hour, both
are kept. Exposed via a FastAPI service and a Next.js dashboard.

See [`PLAN.md`](./PLAN.md) for the original design discussion this was built
from.

## How to run it

**Target state (once Docker Compose is added):**

```bash
docker compose up
```

No manual steps from a fresh clone — Compose brings up Postgres, runs
migrations, seeds the fixed set of cities, and starts both the API and the
dashboard.

**Current state**: Compose isn't built yet. Until then, run it manually:

```bash
# 1. Postgres
docker run -d --name ella-weather-dev-pg \
  -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=ella_weather \
  -p 5432:5432 postgres:16-alpine

# 2. Backend
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
export DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5432/ella_weather"
.venv/bin/alembic upgrade head
# seed locations + run one ingestion cycle - see backend/app/models.py's
# Location and backend/app/ingestion.py's run_ingestion_cycle
.venv/bin/uvicorn app.main:app --reload --port 8000

# 3. Frontend (separate terminal)
cd frontend
npm install
npm run dev   # http://localhost:3000
```

## Architecture / data model

### The dual-timestamp design: `target_time` vs `issued_at`

Every forecast value carries two timestamps, and conflating them is the one
mistake that would break the core requirement of this project:

- **`target_time`** — the hour being forecast (e.g. "tomorrow 2pm").
- **`issued_at`** — when that forecast value was produced (which poll cycle
  observed it).

A naive schema keyed only on `(location, target_time)` would let a later
poll silently overwrite an earlier one — exactly the "yesterday's forecast
for 2pm gets erased by today's forecast for the same 2pm" bug the project
exists to avoid. Keying on `(location, target_time, issued_at)` instead
means every revision is a distinct row: nothing is ever overwritten, and the
full history of how a prediction for a given hour evolved as it got closer
is queryable.

### Tables

- **`locations`** — a small, fixed, seeded set of Belgian cities
  (slug, name, latitude, longitude, timezone). Not user-managed.
- **`ingestion_runs`** — one row per poll attempt per location: `scheduled_for`
  (the deterministic poll slot, see below), `started_at` (wall-clock, for
  logs only), `finished_at`, `status` (`running` / `success` / `failed`),
  `rows_inserted`, `error_message`. This is the operational log.
- **`forecast_values`** — one row per poll per (location, target hour):
  `location_id`, `target_time`, `issued_at`, `ingestion_run_id`, plus the
  weather variables (temperature, precipitation, precipitation probability,
  wind speed/direction, cloud cover, relative humidity, weather code).

`forecast_values.ingestion_run_id` links each forecast row back to the poll
that wrote it. `forecast_values.issued_at` is *copied* from
`ingestion_runs.scheduled_for` — see the constraint discussion below for why
that distinction matters.

### `UNIQUE(location_id, target_time, issued_at)`

This is both the natural key (a given location/hour/issuance should never
appear twice) and the **idempotency key**: ingestion inserts with
`ON CONFLICT (location_id, target_time, issued_at) DO NOTHING`. That only
works because `issued_at` is not a per-row wall-clock timestamp — it's the
deterministic poll slot `floor(now_utc, 6h)`, computed once per poll cycle
in `run_ingestion_cycle` and threaded unchanged into every row that cycle
writes (`app/ingestion.py`). A retried poll cycle recomputes the identical
slot, so its inserts collide harmlessly with rows already written instead of
duplicating them.

**With more time**: the schema does not enforce, at the database level, that
a `forecast_values.issued_at` actually matches its parent
`ingestion_runs.scheduled_for` — nothing stops a hypothetical bug from
writing a row whose `issued_at` disagrees with the run it's linked to via
`ingestion_run_id`. Today this is an application-code guarantee (one
variable, computed once, passed down), not a hard constraint. A trigger (or
a generated/check constraint joining the two tables) would make it
impossible to violate even under a future bug, and is the single change I'd
prioritize next for correctness-under-modification.

## Operational safety

Three properties were treated as requirements, not nice-to-haves, and each
one is backed by a test that exercises the real code path against a real
Postgres — not just reasoning about the constraint in isolation.

- **Idempotency**: `tests/test_ingestion.py::test_retry_with_same_scheduled_for_inserts_zero_new_rows`
  calls `run_ingestion_cycle` twice with the same `now` (same poll slot). The
  first call inserts 3 rows; the second logs its own `IngestionRun` row but
  inserts zero new rows — proven through `run_ingestion_cycle` itself, not by
  hand-crafting SQL and checking the constraint fires.
- **Atomicity**: `tests/test_ingestion.py::test_crash_on_third_location_leaves_first_two_committed_and_logs_the_failure`
  injects a failure partway through a 3-location poll cycle. The first two
  locations are fully committed with complete data; the third location's
  partial attempt — including its own `'running'` `IngestionRun` row — rolls
  back entirely, because nothing for a location commits until that
  location's transaction is entirely done (`ingest_location` in
  `app/ingestion.py`).
- **Resilience**: a failing location doesn't abort the whole poll cycle or
  vanish silently. `ingest_location` catches the failure, rolls back the
  partial attempt, and writes a *separate*, freshly committed
  `IngestionRun` row with `status='failed'` and `error_message` set, then
  the cycle continues to the next location. The same crash test asserts
  exactly one such row exists — not zero (invisible failure), not more than
  one (duplicate logging) — keyed by `location_id`, not list position.

## API design

Three endpoints, deliberately scoped:

- `GET /locations` — the seeded list.
- `GET /locations/{slug}/forecast/current` — latest known value per hour,
  via `DISTINCT ON (target_time) ... ORDER BY target_time, issued_at DESC`.
- `GET /locations/{slug}/forecast/history?target_time=...` — every revision
  ever recorded for one target hour, oldest to newest.

**Error handling reasoning**: an unknown `slug` is a genuine client error —
the resource named by the URL doesn't exist — so it's a `404`. An unmatched
`target_time` on a *real* location is different: the location exists, the
query is well-formed, it just has zero matching rows (that hour may not have
been polled yet, or falls outside the forecast horizon). That's not an
error, so `/forecast/history` returns `200` with an empty list rather than a
`404` in that case — collapsing "malformed request" and "legitimately no
data yet" into the same status code would make `404` responses harder to
act on.

## What was cut, and why

- **`/forecast/as-of?issued_at=...`** — designed in `PLAN.md` (point-in-time
  reconstruction of what the forecast looked like at a given moment), cut
  for time. Not started, not a partial implementation.
- **Revision-history dashboard view** — only the current-forecast view was
  built in the Next.js dashboard. A view for "how did the forecast for this
  hour change over time" (backed by the `/forecast/history` endpoint, which
  does exist) was cut for time.
- **Scheduling mechanism for the 6-hourly poll** (cron / APScheduler /
  external scheduler) — deferred. `run_ingestion_cycle` is a plain function
  that can be invoked by any of those; picking one doesn't affect the schema
  or the ingestion logic, so it was left for whenever the project actually
  needs to run unattended.
- **Retention/pruning job** — intentionally deferred. Nothing is ever
  deleted; the `issued_at` index makes adding a pruning job later
  straightforward without a schema change.

## Data quality note

Precipitation amount (`precipitation_mm`) and precipitation probability
(`precipitation_probability`) are independent outputs of Open-Meteo's
`best_match` model and can look inconsistent at a glance — e.g. a 93% chance
of precipitation with `precipitation_mm = 0.0` for that same hour. This was
verified to be a real characteristic of the upstream model, not a bug in
this pipeline: the exact same `0.0` value is present in Postgres at full
`NUMERIC` precision, was written by `build_forecast_rows` with no rounding
applied anywhere in ingestion, and is rendered by the frontend with no
truncation either. Probability reflects the model's confidence that *some*
measurable precipitation occurs; amount is a separate expected-value
estimate that can legitimately land at zero even when probability is high.

## What I'd do with more time

- **Energy-consumption-relevant insights layered on the weather data** —
  e.g. flagging temperature swings correlated with demand. Raw hourly
  forecast numbers are closer to a weather API demo than to what Ella's
  actual customers would want; the interesting product surface is what the
  weather implies for energy usage, not the weather itself.
- **Dashboard polish** — the current UI is functional (shadcn/ui components,
  a working location picker and forecast table) but visually plain. No time
  was spent on layout, density, or making the data legible at a glance
  beyond a basic table.
- **A DB-level guarantee tying `forecast_values.issued_at` to its parent
  `ingestion_runs.scheduled_for`** — as noted above, this is currently an
  application-code discipline (one value, computed once, threaded through),
  not something the schema itself can enforce. A trigger would remove the
  dependency on that discipline holding under future changes.
