# Instant Food Decision Engine

MVP service that chooses one food place nearby for the user.

## Stack
- FastAPI
- OpenStreetMap (planned via Overpass API)

## Run locally
1. Create virtual environment:
   - `python3 -m venv .venv`
   - `source .venv/bin/activate`
2. Install dependencies:
   - `pip install -r requirements.txt`
3. Start API:
   - `uvicorn app.main:app --reload`
4. Open:
   - `http://localhost:8000/`

## Endpoints
- `GET /` (simple web UI)
- `GET /health`
- `GET /ready` (readiness probe for deployment)
- `POST /v1/decide`

## Scoring weights (optional)
- `DISTANCE_WEIGHT` (default `0.75`)
- `RELIABILITY_WEIGHT` (default `0.25`)

## Run tests
- `make test`
or
- `.venv/bin/python -m unittest discover -s tests -p "test_*.py"`

## Docker deployment
1. Build image:
   - `make docker-build`
2. Run with docker compose:
   - `make docker-up`
3. Check readiness:
   - `curl http://localhost:8000/ready`
4. Open UI:
   - `http://localhost:8000/`
5. Stop containers:
   - `make docker-down`

## Quick API test
```bash
curl -X POST "http://localhost:8000/v1/decide" \
  -H "Content-Type: application/json" \
  -d '{"latitude":50.4501,"longitude":30.5234,"mode":"autopilot"}'
```

## Next
- Improve `opening_hours` parsing for more OSM formats.
- Add tests around `/v1/decide` endpoint with mocked Overpass responses.
- Add mode support (`assisted`, `exploration`) in API and UI.
