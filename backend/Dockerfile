FROM node:22-bookworm-slim AS midscene-runtime

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
WORKDIR /app/midscene
COPY midscene/package*.json ./
RUN npm ci --omit=dev \
    && npx playwright install --only-shell chromium
COPY midscene/midscene_runner.js ./midscene_runner.js

FROM python:3.11-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    HOME=/home/app

WORKDIR /app

COPY requirements.txt .

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates gcc \
    && python -m pip install --upgrade pip \
    && pip install -r requirements.txt \
    && addgroup --system app \
    && adduser --system --ingroup app --home /home/app app \
    && adduser app dialout \
    && mkdir -p /home/app /app /app/reports /app/uploads /app/celery /ms-playwright \
    && chown -R app:app /home/app /app /ms-playwright \
    && chmod 0775 /app/reports \
    && apt-get purge -y gcc \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY app ./app
COPY claw_5skill_final ./claw_5skill_final
COPY claw_5skill_unified ./claw_5skill_unified
COPY ui_case_skills ./ui_case_skills
COPY tests ./tests
COPY pytest.ini ./pytest.ini

RUN chown -R app:app /app

USER app

EXPOSE 8000

FROM base AS runtime

CMD ["sh", "-c", "umask 0002 && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

FROM base AS execution

USER root
COPY --from=midscene-runtime /usr/local/bin/node /usr/local/bin/node
COPY --chown=app:app --from=midscene-runtime /app/midscene /app/midscene
COPY --chown=app:app --from=midscene-runtime /ms-playwright /ms-playwright
RUN python -m playwright install-deps chromium \
    && rm -rf /var/lib/apt/lists/*
USER app

CMD ["sh", "-c", "umask 0002 && exec celery -A app.core.celery_app.celery_app worker -l info --pool=solo -Q execution"]
