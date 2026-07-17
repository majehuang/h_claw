from typing import Any

from app.crawler.orchestrator import CrawlOutcome, CrawlRequest

_VALID_MODES = {"auto", "http", "browser", "stealth"}
_MIN_TIMEOUT = 5
_MAX_TIMEOUT = 90
_SUCCESS_STATUSES = {"SUCCESS", "PARTIAL"}


def build_crawl_response(
    outcome: CrawlOutcome, *, inline_limit_bytes: int, max_markdown_bytes: int
) -> dict[str, Any]:
    """按第 4.1/4.3 节把 CrawlOutcome 映射为 MCP 工具返回：
    - 成功且 Markdown < inline_limit：内联 markdown + resource_uri。
    - 成功且 Markdown >= inline_limit：省略内联正文，只给 resource_uri。
    - 成功但 Markdown > max_markdown：返回 CONTENT_TOO_LARGE。
    - 非成功：统一错误信封（status + error_code + retriable）。
    """
    if outcome.status not in _SUCCESS_STATUSES:
        return {
            "status": outcome.status,
            "job_id": outcome.job_id,
            "source_url": outcome.source_url,
            "error_code": outcome.error_code,
            "error_message": outcome.error_message,
            "retriable": outcome.retriable,
            "retry_after_seconds": outcome.retry_after_seconds,
        }

    markdown = outcome.markdown or ""
    byte_length = len(markdown.encode("utf-8"))

    if byte_length > max_markdown_bytes:
        return {
            "status": "FAILED",
            "job_id": outcome.job_id,
            "source_url": outcome.source_url,
            "error_code": "CONTENT_TOO_LARGE",
            "error_message": (
                f"Markdown 大小 {byte_length} 字节超过上限 {max_markdown_bytes} 字节。"
            ),
            "retriable": False,
            "retry_after_seconds": None,
            "markdown": None,
            "resource_uri": outcome.resource_uri,
        }

    response: dict[str, Any] = {
        "status": outcome.status,
        "job_id": outcome.job_id,
        "title": outcome.title,
        "source_url": outcome.source_url,
        "final_url": outcome.final_url,
        "fetch_mode": outcome.fetch_mode,
        "resource_uri": outcome.resource_uri,
        "content_length": byte_length,
        "warnings": [],
    }
    response["markdown"] = markdown if byte_length < inline_limit_bytes else None
    return response


async def crawl_url_impl(
    service: Any,
    *,
    url: str,
    mode: str,
    include_images: bool,
    force_refresh: bool,
    timeout_seconds: int,
) -> dict[str, Any]:
    if mode not in _VALID_MODES:
        raise ValueError(f"不支持的 mode: {mode!r}，允许值 {sorted(_VALID_MODES)}")
    if not _MIN_TIMEOUT <= timeout_seconds <= _MAX_TIMEOUT:
        raise ValueError(
            f"timeout_seconds 必须在 [{_MIN_TIMEOUT}, {_MAX_TIMEOUT}] 之间"
        )

    request = CrawlRequest(
        url=url,
        mode=mode,
        include_images=include_images,
        force_refresh=force_refresh,
        timeout_seconds=timeout_seconds,
    )
    outcome = await service.orchestrator.crawl(request)
    return build_crawl_response(
        outcome,
        inline_limit_bytes=service.inline_limit_bytes,
        max_markdown_bytes=service.max_markdown_bytes,
    )
