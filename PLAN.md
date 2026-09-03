# Ella Weather — Plan

Ingests Belgian weather forecasts from Open-Meteo into PostgreSQL, preserving every
forecast revision per target hour (a forecast issued today for tomorrow 2pm never
overwrites yesterday's forecast for that same hour). Exposed via a FastAPI service
and a Next.js dashboard.

## Decisions locked in with the user

- **Locations**: small fixed set of Belgian cities, seeded via config — not a
  user-managed CRUD surface (yet).
- **Variables**: temperature, precipitation, precipitation probability, wind
  speed/direction, cloud cover, relative humidity.
- **Horizon/model**: hourly resolution, 7-day horizon, Open-Meteo's `best_match`
  model.
- **Verification data**: out of scope for now — forecasts only, no ingestion of
  observed/actual weather.
- **Poll cadence**: every 6 hours.
- **Revision granularity**: insert every poll's fetched row unconditionally
  (no value-diffing) — simpler for the timebox, and safe because `issued_at`
  is a deterministic per-cycle slot rather than a wall-clock timestamp (see
  below), so retries can't create duplicates. Value-diffing dedup is a cut
  stretch goal (call it out in the README).
- **Retention**: keep everything forever for now; schema should not preclude
  adding a pruning job later.

## Data model

### `locations`
Fixed seed set (e.g. Brussels, Antwerp, Ghent, Liège, Bruges).

| column      | type        | notes                          |
|-------------|-------------|---------------------------------|
| id          | smallserial | PK                              |
| slug        | text        | unique, e.g. `brussels`         |
| name        | text        | display name                    |
| latitude    | numeric     |                                  |
| longitude   | numeric     |                                  |
| timezone    | text        | IANA tz, `Europe/Brussels`      |

### `ingestion_runs`
Operational log of each poll attempt, independent of the forecast data itself —
gives observability without polluting `forecast_values`.

| column          | type        | notes                                                        |
|-----------------|-------------|----------------------------------------------------------------|
| id              | bigserial   | PK                                                              |
| location_id     | smallint    | FK → locations                                                  |
| scheduled_for   | timestamptz | **deterministic poll slot** — `floor(now_utc, 6h)`, computed once per poll cycle *before* any location is fetched, and shared by every location in that cycle. This is what becomes `forecast_values.issued_at`. |
| started_at      | timestamptz | actual wall-clock time this run began — for logs/debugging only, never used as a data key |
| finished_at     | timestamptz | null if still running/crashed                                   |
| status          | text        | `success` / `failed`                                            |
| rows_inserted   | int         | rows written this run                                           |
| error_message   | text        | null on success                                                 |

**Why `scheduled_for` is separate from `started_at`**: `started_at` is
wall-clock and different every time a run is attempted, including retries of
the same logical poll. `scheduled_for` is deterministic — the same crashed
poll cycle, retried five minutes or five hours later, recomputes the same
slot (as long as it's before the next 6h boundary), which is what makes
inserts idempotent (see `forecast_values` below).

### `forecast_values`
The core revision-tracked table. One row per **poll** per (location,
target_hour) — every poll writes a row unconditionally, whether or not the
value changed since the last poll (see "Change-detection" below for why).

| column                    | type        | notes                                              |
|---------------------------|-------------|-----------------------------------------------------|
| id                        | bigserial   | PK                                                    |
| location_id               | smallint    | FK → locations                                        |
| target_time               | timestamptz | the forecasted hour, UTC                              |
| issued_at                 | timestamptz | copied from `ingestion_runs.scheduled_for` for the run that wrote this row — a deterministic poll slot, **not** a per-row wall-clock timestamp. Every row inserted by the same poll cycle (across all locations) shares the same `issued_at`. |
| ingestion_run_id          | bigint      | FK → ingestion_runs (which poll produced this row)     |
| temperature_c             | numeric     |                                                        |
| precipitation_mm          | numeric     |                                                        |
| precipitation_probability | smallint    | percent, 0–100                                        |
| wind_speed_kmh            | numeric     |                                                        |
| wind_direction_deg        | smallint    |                                                        |
| cloud_cover_pct           | smallint    |                                                        |
| relative_humidity_pct     | smallint    |                                                        |
| weather_code              | smallint    | Open-Meteo WMO code, for icon/condition display       |

Constraints/indexes:
- `UNIQUE (location_id, target_time, issued_at)` — this is also the
  **idempotency key**: insert with `ON CONFLICT (location_id, target_time,
  issued_at) DO NOTHING`. Because `issued_at` is the deterministic
  `scheduled_for` slot rather than wall-clock time, a retried/re-run poll
  cycle recomputes the same slot and its inserts simply no-op against rows
  already written — no duplicate rows from crash-retries.
- Index on `(location_id, target_time, issued_at DESC)` — powers both "latest
  value for this hour" and "full revision history for this hour" queries.
- Index on `issued_at` — powers "reconstruct the forecast as it looked at time
  T" queries and any future retention/pruning job.

**Why no separate `forecast_runs` table for the data itself**: `ingestion_runs`
already carries one row per (location, poll cycle) for operational logging;
adding a second run-shaped table just for the data would be redundant.
`forecast_values.ingestion_run_id` traces any row back to the poll that wrote
it.

**Change-detection: cut for now, unconditional insert instead.** Originally
planned as "only insert if the value differs from the last-stored one," but
given the timebox this is simplified to inserting every poll's fetched value
unconditionally. This is safe: every derived query below already orders by
`issued_at` and doesn't assume gaps between polls, so nothing breaks — the
only cost is more rows (trivial at this scale: 5 locations × ~168 hourly
points × 4 polls/day ≈ 3,360 rows/day) and a revision-history view that shows
flat repeated values between actual changes rather than only the change
points. **This relies on the `issued_at`-as-slot fix above** — unconditional
insert with a wall-clock `issued_at` would duplicate rows on every retry;
with a slot-based `issued_at` and `ON CONFLICT DO NOTHING` it's idempotent.
Value-diffing dedup is a cut stretch goal — note it in the README as
"not implemented" rather than silently dropping it.

### Derived queries (no extra tables needed)

- **Current forecast** (what do we believe right now): `DISTINCT ON
  (location_id, target_time) ... ORDER BY location_id, target_time,
  issued_at DESC`.
- **Revision history for one hour**: `WHERE location_id = ? AND target_time = ?
  ORDER BY issued_at`.
- **Forecast as it stood at time T** (point-in-time reconstruction): `DISTINCT
  ON (location_id, target_time) ... WHERE issued_at <= T ORDER BY location_id,
  target_time, issued_at DESC`.

## Ingestion job

- Standalone module (not inside the FastAPI request path) sharing the same
  SQLAlchemy models as the API.
- Triggered every 6 hours (cron / scheduled container / APScheduler — TBD at
  build time, doesn't affect the schema).
- One poll cycle:
  1. Compute `scheduled_for = floor(now_utc, 6h)` **once**, before touching
     any location.
  2. For each location: open an `ingestion_runs` row (`scheduled_for`,
     `started_at = now()`), call the Open-Meteo hourly forecast endpoint
     (`model=best_match`, 7-day horizon, the six tracked variables), insert
     one `forecast_values` row per returned hour with
     `issued_at = scheduled_for`, using `ON CONFLICT (location_id,
     target_time, issued_at) DO NOTHING` — unconditional insert, idempotent
     on retry. Close the run with status and `rows_inserted`.
  3. A crashed run can simply be re-triggered (whole cycle or a single
     failed location); recomputing `scheduled_for` from the same formula
     reproduces the same slot as long as the next 6h boundary hasn't passed,
     so retried inserts collide harmlessly with ones already written.

## API (FastAPI)

- `GET /locations` — seeded list.
- `GET /locations/{slug}/forecast/current` — latest known value per hour, next
  7 days.
- `GET /locations/{slug}/forecast/history?target_time=...` — all revisions for
  one target hour.
- `GET /locations/{slug}/forecast/as-of?issued_at=...` — reconstructed forecast
  as it looked at a given moment.

## Dashboard (Next.js)

- Location picker (from the fixed seed set).
- Current 7-day hourly forecast view.
- A revision view for a selected hour: how the prediction for e.g. "tomorrow
  2pm" evolved across successive polls, so drift/accuracy is visible before
  the hour arrives.

## Open items / assumptions to revisit

- Exact seed list of cities and their coordinates.
- Scheduling mechanism for the 6-hourly poll (cron vs APScheduler vs external
  scheduler) — deferred to implementation, doesn't change the schema.
- Retention/pruning job — intentionally deferred; `issued_at` index makes it
  straightforward to add later.
- **Cut for timebox — call out in README**: value-diffing dedup on
  `forecast_values` (only insert when the fetched value differs from the
  last one) was cut in favor of unconditional insert-every-poll. Revisit if
  row volume ever becomes a real concern (it won't at this scale).
