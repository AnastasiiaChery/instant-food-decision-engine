# Instant Food Decision Engine

AI-powered service that finds and recommends food and drink venues nearby. Enter a free-text query ("cozy Italian", "cocktails", "romantic dinner at 20:00") — the service fetches nearby places from OpenStreetMap, parses your intent with an LLM, and streams back AI-ranked results in real time. Irrelevant places are filtered out; top 5 shown by default with a "Show more" option.

## Stack

| Layer | Tech |
|-------|------|
| API | FastAPI + Uvicorn |
| AI | Groq `llama-3.3-70b-versatile` via OpenAI-compatible SDK |
| Geo | OpenStreetMap / Overpass API (2 failover endpoints) |
| Auth | Google OAuth2 + email/password + JWT (python-jose, passlib/bcrypt) |
| DB | PostgreSQL 16 + SQLAlchemy 2 async + Alembic |
| Cache | Redis (optional — degrades gracefully) |
| Frontend | Vanilla JS + Leaflet maps |
| Infra | Docker + Docker Compose |

## How it works

```
POST /api/v1/search
  │
  ├─ LLM parses query → venue_types (restaurant/bar/pub/cafe/…), cuisine, mood
  ├─ Overpass fetches venues in parallel (bar for cocktails, pub for beer, etc.)
  ├─► SSE "places" — raw results, immediate
  ├─ LLM ranks each place 0–1, explains why
  ├─ Filters out score < 0.2, sorts by relevance then distance
  └─► SSE "ranked" — top results, ~1-2s later
```

Three UI modes: **Autopilot** (AI picks one best option), **Preferences** (query + chips + radius), **Plan** (when, group size, occasion, radius).

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

Open `http://localhost:8000`

### Environment variables

Copy `.env.example` → `.env`:

```
GROQ_API_KEY=...
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/callback
JWT_SECRET=change-me-in-prod
```

Optional (shown with defaults):
```
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/instantfood
REDIS_URL=                    # empty = no cache
SEARCH_RADIUS_M=1500          # initial search radius
MAX_RADIUS_M=3000             # hard cap (user slider 0.5–3 km)
JWT_EXPIRE_MINUTES=10080      # 7 days
```

## Search request

`POST /api/v1/search` accepts:

| Field | Type | Description |
|-------|------|-------------|
| `lat` | float | Latitude |
| `lng` | float | Longitude |
| `query` | string | Free-text ("cocktails", "cozy Italian", …) |
| `when` | string? | `"HH:MM"` — plan for a specific time |
| `radius_m` | int? | Search radius in metres, capped at `MAX_RADIUS_M` |

Streams two SSE events: `places` (raw list) then `ranked` (AI-scored, filtered, sorted).

## Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/` | — | Web UI |
| `GET` | `/health` | — | Health check |
| `GET` | `/ready` | — | Readiness probe |
| `POST` | `/api/v1/search` | — | Search + AI ranking (SSE), 10 req/min |
| `POST` | `/v1/decide` | — | Legacy single-result endpoint |
| `GET` | `/auth/google` | — | Start Google OAuth flow |
| `GET` | `/auth/callback` | — | OAuth callback → JWT |
| `POST` | `/auth/register` | — | Email/password registration → JWT |
| `POST` | `/auth/login` | — | Email/password login → JWT |
| `POST` | `/api/v1/history/navigate` | ✓ | Record navigate or favourite |
| `GET` | `/api/v1/history` | ✓ | Last 50 history entries |
| `GET` | `/api/v1/profile/preferences` | ✓ | Get user preferences |
| `PUT` | `/api/v1/profile/preferences` | ✓ | Update diet + cuisines |
| `PUT` | `/api/v1/profile/me` | ✓ | Update display name |

## Auth

**Google OAuth:**
1. Sign in → "Continue with Google" → `/auth/google`
2. Callback at `/auth/callback?code=...` → upsert user → JWT via `/?token=<jwt>`

**Email / password:**
- `POST /auth/register` → bcrypt hash → JWT (409 on duplicate email)
- `POST /auth/login` → verify hash → JWT

JWT stored in `localStorage`, sent as `Authorization: Bearer <token>`. Signed-in users see a user drawer with Profile and History tabs.

## Database

Alembic manages migrations; they run automatically on container start.

```bash
alembic upgrade head                              # apply all
alembic revision --autogenerate -m "description"  # new migration
```

Tables: `users` (`password_hash`, `preferences` JSON), `search_history` (`action_type`, `place_notes`).

## Tests

```bash
python -m unittest discover tests -v
# or
make test
```

## Docker

```bash
docker compose up --build      # build + start (runs migrations automatically)
docker compose down
curl http://localhost:8000/ready
```
