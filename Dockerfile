FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /srv/app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app

RUN uv sync --frozen --no-dev \
    && useradd --create-home --uid 1000 crawler \
    && mkdir -p /data \
    && chown -R crawler:crawler /data /srv/app

ENV PATH="/srv/app/.venv/bin:${PATH}"
ENV DATA_DIR=/data

USER crawler

EXPOSE 8000

CMD ["python", "-m", "app.main"]
