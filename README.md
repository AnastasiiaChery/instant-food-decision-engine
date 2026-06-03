# Instant Food Decision Engine

AI-powered service that finds and recommends a food place nearby using your location.

## Stack

| Layer | Tech |
|-------|------|
| API | FastAPI |
| AI | Groq (llama-3.3-70b) via OpenAI-compatible SDK |
| Geo | OpenStreetMap via Overpass API |
| Auth | Google OAuth2 + email/password + JWT (python-jose, passlib) |
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
| `POST` | `/auth/register` | Email/password registration → JWT |
| `POST` | `/auth/login` | Email/password login → JWT |
| `POST` | `/api/v1/history/navigate` | Record navigate or favourite (auth required) |
| `GET` | `/api/v1/history` | Get last 50 history entries (auth required) |
| `GET` | `/api/v1/profile/preferences` | Get user preferences (auth required) |
| `PUT` | `/api/v1/profile/preferences` | Update diet, cuisines (auth required) |
| `PUT` | `/api/v1/profile/me` | Update display name (auth required) |

## Auth flow

**Google OAuth:**
1. User clicks **Sign in** → modal opens → "Continue with Google" → `/auth/google`
2. Google bounces to `/auth/callback?code=...`
3. Server upserts user, returns JWT via `/?token=<jwt>`

**Email/password:**
1. User opens modal → Register tab → fills email + password
2. `POST /auth/register` → returns JWT
3. Or existing user: Sign in tab → `POST /auth/login` → returns JWT

Frontend stores JWT in `localStorage`. Signed-in users see their email in the header; clicking it opens the **User Drawer** with Profile and History tabs.

## Database

Migrations are managed with Alembic:

```bash
alembic upgrade head          # apply all migrations
alembic revision --autogenerate -m "description"  # create new migration
```

Tables: `users` (with `password_hash`), `search_history` (with `action_type`: `navigate` | `favorite`)

## Run tests

```bash
python -m unittest discover tests -v
# or
make test
```

## Docker deployment

```bash
docker compose build
docker compose up -d
curl http://localhost:8000/ready
docker compose down
```

Migrations run automatically on container start via `entrypoint.sh`.
