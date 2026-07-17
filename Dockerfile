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

# 安装 Chromium 及其系统依赖。scrapling install 执行 playwright install chromium
# + install-deps（需 root），写入 /ms-playwright。三层抓取共用这一个 chromium
# 二进制：HTTP 用 curl_cffi（无需浏览器）、DynamicFetcher 用 playwright chromium、
# StealthyFetcher 用 patchright chromium——patchright 复用同版本 playwright chromium
# （chromium-1228），因此无需额外下载 camoufox 或第二套浏览器。
RUN uv run scrapling install \
    && uv run patchright install chromium \
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
