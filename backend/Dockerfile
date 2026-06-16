FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

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

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
