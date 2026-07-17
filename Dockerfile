FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /srv/app

# 浏览器二进制放到共享、全局可读的路径，便于非 root 用户运行时读取。
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# 安装 Chromium 及其系统依赖（DynamicFetcher 用）。scrapling install 会执行
# playwright install chromium + install-deps（需 root），并写入 /ms-playwright。
# 隐身层（StealthyFetcher）依赖的 camoufox 为按需下载，容器内 stealth 支持
# 在 M10 容器化验收阶段单独补齐（camoufox fetch 到共享路径），此处先保证
# HTTP 与浏览器两层可用。
RUN uv run scrapling install \
    && chmod -R a+rX /ms-playwright

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
