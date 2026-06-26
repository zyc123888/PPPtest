FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    HOME=/home/app

WORKDIR /app

COPY requirements.txt .

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates gcc nodejs npm \
    && python -m pip install --upgrade pip \
    && pip install -r requirements.txt \
    && npm install -g xmindmark \
    && xmindmark --version \
    && python -m playwright install --with-deps chromium \
    && addgroup --system app \
    && adduser --system --ingroup app --home /home/app app \
    && mkdir -p /home/app /app /app/reports /ms-playwright \
    && chown -R app:app /home/app /app /ms-playwright \
    && chmod -R 777 /app/reports \
    && apt-get purge -y gcc \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY app ./app
COPY claw_5skill_final ./claw_5skill_final
COPY tests ./tests
COPY pytest.ini ./pytest.ini

RUN chown -R app:app /app

USER app

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
