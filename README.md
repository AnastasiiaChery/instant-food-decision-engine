# Instant Food Decision Engine

AI-powered service that finds and recommends a food place nearby using your location.

## Stack

| Layer | Tech |
|-------|------|
| API | FastAPI |
| AI | Groq (llama-3.3-70b) via OpenAI-compatible SDK |
| Geo | OpenStreetMap via Overpass API |
| Auth | Google OAuth2 + JWT (python-jose) |
| DB | PostgreSQL 16 + SQLAlchemy 2 async + Alembic |
| Cache | Redis |
| Frontend | Vanilla JS + Leaflet |

## Run locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Start dependencies
docker compose up postgres redis -d

# Apply DB migrations
alembic upgrade head

# Start server
uvicorn app.main:app --reload
```

Open `http://localhost:8000/`

### Required env vars (copy `.env.example` → `.env`)

```
GROQ_API_KEY=...
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/callback
JWT_SECRET=change-me-in-prod
```

Optional:
```
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/instantfood
JWT_EXPIRE_MINUTES=10080
DISTANCE_WEIGHT=0.75
RELIABILITY_WEIGHT=0.25
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Web UI |
| `GET` | `/health` | Health check |
| `GET` | `/ready` | Readiness probe |
| `POST` | `/api/v1/search` | Search + AI ranking (SSE stream) |
| `POST` | `/api/v1/decide` | Legacy single-result endpoint |
| `GET` | `/auth/google` | Start Google OAuth flow |
| `GET` | `/auth/callback` | OAuth callback → issues JWT |
| `POST` | `/api/v1/history/navigate` | Record a Navigate click (auth required) |

## Auth flow

1. User clicks **Sign in** → redirected to `/auth/google` → Google login
2. Google bounces to `/auth/callback?code=...`
3. Server exchanges code for user info, upserts user in DB, returns JWT via `/?token=<jwt>`
4. Frontend stores JWT in `localStorage`; subsequent Navigate clicks POST to `/api/v1/history/navigate`

## Database

Migrations are managed with Alembic:

```bash
alembic upgrade head          # apply all migrations
alembic revision --autogenerate -m "description"  # create new migration
```

Tables: `users`, `search_history`

## Run tests

```bash
python -m unittest discover tests -v
# or
make test
```

## Docker deployment

```bash
make docker-build
make docker-up
curl http://localhost:8000/ready
make docker-down
```
