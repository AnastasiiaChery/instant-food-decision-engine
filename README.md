# NomPilot — AI Dining Autopilot

> Formerly *Instant Food Decision Engine* — the codename lives on in the package/DB names.

AI-powered service that finds and recommends food and drink venues nearby. Enter a free-text query ("cozy Italian", "cocktails", "romantic dinner at 20:00") — the service fetches nearby places from OpenStreetMap, parses your intent with an LLM, and streams back AI-ranked results in real time.

## Stack

| Layer | Tech |
|-------|------|
| API | FastAPI + Uvicorn |
| AI | Groq `llama-3.3-70b-versatile` via LangChain |
| Geo | OpenStreetMap / Overpass API (2 failover endpoints) |
| Auth | Google OAuth2 + email/password + JWT (python-jose, passlib/bcrypt) |
| DB | PostgreSQL 16 + SQLAlchemy 2 async + Alembic |
| Cache | Redis (optional — degrades gracefully) |
| Tracing | LangSmith (optional) |
| Frontend | Vanilla JS + Leaflet maps |
| Infra | Docker + Docker Compose |

## How it works

Unauthenticated visitors see a landing page. Sign-in is required to access the search UI (enforced client-side; the API itself accepts unauthenticated requests but ignores saved preferences).

```
POST /api/v1/search
  │
  ├─ LLM parses query → venue_types, cuisine, mood, features
  ├─► SSE "intent"   — emitted immediately after parsing
  ├─ Overpass fetches only matched venue types (1–3 instead of ~13), deduped
  ├─ Heuristic pre-sort by distance · mood · cuisine · features → top 30
  ├─► SSE "places"
  │
  ├─ [autopilot]  LLM ranks, picks top 1 + fallback
  │   └─► SSE "recommendation"
  │
  └─ [plan]  agentic planner (may call search_more_places ×2) → finalize_plan
      └─► SSE "recommendations"

  On no relevant results (best score < 0.4):
      └─► SSE "no_match"
```

Two UI modes — see [UI modes](#ui-modes) below.

### Venue types

The following OSM amenity types are recognised: `restaurant` · `fast_food` · `cafe` · `bar` · `pub` · `biergarten` · `food_court` · `cocktail_bar` · `wine_bar` · `juice_bar` · `ice_cream` · `food_hall` · `taproom`. Intent parsing maps the user query to 1–3 of these; if none match, the fallback set is `restaurant, cafe, bar, pub`.

### Geo resilience

Overpass queries try two public endpoints (`overpass-api.de` → `overpass.kumi.systems`), 15 s timeout each. If fewer than 5 venues are found within the requested radius, the radius is automatically expanded to `MAX_RADIUS_M`. If the time-based "open now" filter still yields nothing, it is relaxed to exclude only places explicitly marked `closed` / `off`.

## UI modes

### Autopilot
One tap — AI picks the single best place nearby based on your location. No configuration needed. Returns one curated recommendation with a fallback option and a navigation link. "Try again" skips the previous suggestion.

### Plan
Structured planning for a specific outing:

| Parameter | Options |
|-----------|---------|
| **When** | Right now · Breakfast · Lunch · Dinner · Pick time (HH:MM) |
| **Group** | Solo · 2 people · Small group · Large group |
| **Budget** | Any · € Budget · €€ Mid-range · €€€ Upscale |
| **Preferences** | Optional free text (dietary needs, vibe, cuisine) |
| **Location** | GPS · Address · Click on map |
| **Radius** | 0.5 km to 3 km slider |

The AI is an agentic planner: it first ranks the fetched candidates, then — if the initial list lacks suitable options for the occasion and group — calls `search_more_places` up to 2 times to expand the search before producing a final curated shortlist of 3–5 picks.

---

## Run locally

```bash
make venv && source .venv/bin/activate
make install

# Start dependencies
docker compose up postgres redis -d

# Apply DB migrations
alembic upgrade head

make run          # uvicorn with --reload on :8000
```

Open `http://localhost:8000`

Other Makefile targets: `make test` · `make redis` (standalone Redis container) · `make docker-up` / `make docker-down`

### Environment variables

Copy `.env.example` → `.env`:

```
GROQ_API_KEY=...
AI_BASE_URL=https://api.groq.com/openai/v1   # any OpenAI-compatible endpoint
AI_MODEL=llama-3.3-70b-versatile

GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/callback
JWT_SECRET=change-me-in-prod
```

Optional (shown with defaults):
```
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/instantfood
REDIS_URL=                    # empty = no cache; TTL is 20 min when set
SEARCH_RADIUS_M=1500          # initial search radius
MAX_RADIUS_M=3000             # hard cap (user slider 0.5–3 km)
JWT_EXPIRE_MINUTES=10080      # 7 days

# LangSmith tracing
LANGSMITH_API_KEY=            # empty = tracing disabled
LANGSMITH_TRACING=true
LANGSMITH_PROJECT=instant-food-decision-engine
```

## Search request

`POST /api/v1/search` accepts:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `lat` | float | required | Latitude |
| `lng` | float | required | Longitude |
| `query` | string | `"something good nearby"` | Free-text intent |
| `mode` | string | `"autopilot"` | `autopilot` · `plan` |
| `when` | string? | — | Local time `"HH:MM"` or named (`"breakfast"`, `"lunch"`, `"dinner"`) |
| `radius_m` | int? | `SEARCH_RADIUS_M` | Search radius in metres, capped at `MAX_RADIUS_M` |
| `use_profile` | bool | `true` | Apply saved diet/cuisine preferences when user is authenticated |
| `group_size` | string? | — | Plan mode: `solo` · `duo` · `small_group` · `large_group` |
| `budget` | string? | — | Plan mode: `budget` · `mid` · `upscale` |
| `exclude_place_names` | string[] | `[]` | Autopilot: skip these venues (for "try again") |
| `exclude_place_name` | string? | — | Autopilot: skip one venue (legacy, single) |

### SSE event stream

The response is a Server-Sent Events stream. Events arrive in this order:

| Event | Modes | Payload |
|-------|-------|---------|
| `intent` | all | `{ query, venue_types, mood, cuisine, features }` |
| `places` | all | `[{ name, distance_m, amenity, cuisine, lat, lon, nav_url }]` |
| `recommendation` | autopilot | `{ place, reason, signals, fallback_place, fallback_signals }` |
| `recommendations` | plan | `{ recommendations: [{ place, reason, scenario }] }` |
| `no_match` | all | `{ query }` — emitted when best score < 0.4 |
| `error` | all | `{ detail }` |

## Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/` | — | Web UI (landing for guests, app for signed-in users) |
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
3. First login with empty preferences → redirect to `/profile/setup` for onboarding

**Email / password:**
- `POST /auth/register` → bcrypt hash → JWT (409 on duplicate email)
- `POST /auth/login` → verify hash → JWT

JWT stored in `localStorage`, sent as `Authorization: Bearer <token>`. Guests see a landing page with sign-in / register prompts. Signed-in users see an avatar menu with Profile and History tabs.

The search UI is hidden behind auth client-side — guests cannot run searches. The `/api/v1/search` endpoint itself accepts unauthenticated requests (saved preferences are simply not applied).

### User preferences

`PUT /api/v1/profile/preferences` accepts:

```json
{
  "diet": ["vegetarian"],
  "cuisines_liked": ["italian", "thai"],
  "cuisines_disliked": ["sushi"]
}
```

When `use_profile: true` and the user is authenticated, these are injected into the ranking and planning prompts.

### History actions

`POST /api/v1/history/navigate` accepts `action_type`: `"navigate"` (default, records a click to maps) or `"favorite"` (marks a place as starred). Both appear in `GET /api/v1/history` sorted newest-first (last 50 entries).

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
