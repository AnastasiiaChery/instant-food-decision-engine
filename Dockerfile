FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    WEB_CONCURRENCY=4

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY static ./static
COPY README.md ./README.md
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini

# Run as an unprivileged user. Created after COPY so the image layers stay root-owned
# (read-only at runtime); the app process itself never needs write access to them.
RUN useradd --create-home --uid 1000 appuser
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready')"

# Migrations run once before the workers start. WEB_CONCURRENCY controls the uvicorn
# worker count (override per deploy); rate limiting stays correct across workers via Redis.
# --proxy-headers + --forwarded-allow-ips makes uvicorn trust the platform load
# balancer's X-Forwarded-For so the per-IP rate limiter keys on the real client IP
# instead of bucketing every request under the proxy address.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers ${WEB_CONCURRENCY} --proxy-headers --forwarded-allow-ips=${FORWARDED_ALLOW_IPS:-*}"]
