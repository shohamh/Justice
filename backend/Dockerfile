FROM python:3.12-slim AS production

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Jerusalem

# date.today()/datetime.now() are used throughout the backend for "today"
# cutoffs and status transitions (range events, duty rosters, dashboards).
# python:3.12-slim has no tzdata, so without it the TZ env var above is
# silently ignored and the container clock stays on UTC — 2-3 hours behind
# Israel, which mis-times any comparison that happens near local midnight.
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Set to your PyPI mirror URL to use a private/corporate index.
# e.g.: docker build --build-arg PIP_INDEX_URL=https://your.mirror/simple/ .
# pip reads PIP_INDEX_URL from the environment automatically.
ARG PIP_INDEX_URL=https://pypi.org/simple/
ENV PIP_INDEX_URL=$PIP_INDEX_URL

COPY pyproject.toml ./
RUN pip install --no-cache-dir .

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
