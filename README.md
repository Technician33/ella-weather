###Tools
Python
Fast API
SQLAlchemy
PostgresSQL

Next.js
Typescript

Docker (+compose)

Open-meteo API

###doel
Deze software neemt Belgische weersvoorspellingen op uit Meteo-open API en plaatst ze in een database van PostgresSQL. 
Deze database moet vervolgens kunnen communiceren met een fastapi backend, om de data in een next.js frontend te kunnen displayen.

###Architectuur

```mermaid
flowchart LR
    OM["☁️ Open-Meteo API"]

    subgraph ingestor["Ingestor (Python)"]
        ING["every 6h"]
    end

    subgraph db["PostgreSQL"]
        LOC["locations"]
        RUNS["ingestion_runs"]
        VALS["forecast_values"]
    end

    subgraph api["FastAPI :8000"]
        E1["GET /locations"]
        E2["GET /forecast/current"]
        E3["GET /forecast/history"]
    end

    subgraph ui["Next.js :3000"]
        DASH["Dashboard"]
    end

    OM -->|"hourly forecasts"| ING
    ING --> RUNS
    ING --> VALS
    VALS --> E1
    VALS --> E2
    VALS --> E3
    E1 --> DASH
    E2 --> DASH
    E3 --> DASH
    LOC --> E1
```

###Software runnen

```bash
docker compose up
```

Dit start de API en het dashboard op localhost:8000 en localhost:3000, respectievleijk.

###API design
| Endpoint | Antwoord |
|---|---|
| `GET /locations` | Beschikbare steden |
| `GET /locations/{slug}/forecast/current` | Hoe ziet de weersvoorspelling eruit |
| `GET /locations/{slug}/forecast/history?target_time=` | Hoe is de weersvoorspelling over tijd geevolueerd |