# hormuz_watch/Dockerfile
#
# One image, three services (see docker-compose.yml): dashboard, api,
# pipeline. Each overrides CMD via docker-compose's `command:`.
#
# NOTE: requirements.txt includes transformers/torch (Phase 4, not used by
# any code yet) which makes this image large (~3-4GB) and slow to build the
# first time. That's the single source-of-truth tradeoff — see requirements.txt.

FROM python:3.11-slim

WORKDIR /app

# gcc/libpq-dev: needed to build psycopg2/xgboost native deps.
# curl: used by the dashboard/api healthchecks defined in docker-compose.yml.
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default command — overridden per-service in docker-compose.yml.
CMD ["streamlit", "run", "dashboard/app.py", "--server.port=8501", "--server.address=0.0.0.0"]
