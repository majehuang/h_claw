FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /srv/app

# 浏览器二进制放到共享、全局可读的路径，便于非 root 用户运行时读取。
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV CAMOUFOX_DOWNLOAD_PATH=/ms-camoufox

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# 安装浏览器运行所需的系统依赖与浏览器二进制（Chromium + camoufox）。
# playwright install-deps 需要 root；scrapling install 下载全部 Fetcher 依赖。
RUN uv run playwright install-deps chromium \
    && uv run scrapling install \
    && chmod -R a+rX /ms-playwright /ms-camoufox

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
