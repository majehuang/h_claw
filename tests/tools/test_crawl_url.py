import pytest

from app.crawler.orchestrator import CrawlOutcome, CrawlRequest
from app.tools.crawl_url import build_crawl_response, crawl_url_impl


def _success_outcome(markdown: str) -> CrawlOutcome:
    return CrawlOutcome(
        status="SUCCESS",
        job_id="cr_1",
        source_url="https://shop.example.com/p/1",
        final_url="https://shop.example.com/p/1",
        fetch_mode="browser",
        title="商品",
        markdown=markdown,
        content_length=len(markdown),
        resource_uri="crawl://results/cr_1/content.md",
    )


def test_small_markdown_is_inlined():
    response = build_crawl_response(
        _success_outcome("# 商品\n\n价格 199"),
        inline_limit_bytes=51200,
        max_markdown_bytes=2097152,
    )
    assert response["status"] == "SUCCESS"
    assert response["markdown"] == "# 商品\n\n价格 199"
    assert response["resource_uri"] == "crawl://results/cr_1/content.md"
    assert response["content_length"] == len("# 商品\n\n价格 199".encode())


def test_large_markdown_omits_inline_body():
    big = "# 大\n" + ("商品描述文字。" * 5000)
    response = build_crawl_response(
        _success_outcome(big), inline_limit_bytes=51200, max_markdown_bytes=2097152
    )
    assert response["markdown"] is None
    assert response["resource_uri"] == "crawl://results/cr_1/content.md"
    assert response["content_length"] == len(big.encode())


def test_oversized_markdown_returns_content_too_large():
    huge = "x" * 100
    response = build_crawl_response(
        _success_outcome(huge), inline_limit_bytes=51200, max_markdown_bytes=50
    )
    assert response["status"] == "FAILED"
    assert response["error_code"] == "CONTENT_TOO_LARGE"
    assert response.get("markdown") is None


def test_error_outcome_maps_to_error_envelope():
    outcome = CrawlOutcome(
        status="BLOCKED",
        job_id="cr_2",
        source_url="https://shop.example.com/p/1",
        error_code="UPSTREAM_BLOCKED",
        error_message="全部层级被拦截",
        retriable=False,
    )
    response = build_crawl_response(
        outcome, inline_limit_bytes=51200, max_markdown_bytes=2097152
    )
    assert response["status"] == "BLOCKED"
    assert response["error_code"] == "UPSTREAM_BLOCKED"
    assert response["retriable"] is False
    assert "markdown" not in response


class FakeOrchestrator:
    def __init__(self, outcome):
        self.outcome = outcome
        self.requests: list[CrawlRequest] = []

    async def crawl(self, request, session=None):
        self.requests.append(request)
        return self.outcome


class FakeService:
    def __init__(self, outcome):
        self.orchestrator = FakeOrchestrator(outcome)
        self.inline_limit_bytes = 51200
        self.max_markdown_bytes = 2097152


@pytest.mark.asyncio
async def test_crawl_url_impl_passes_request_fields_to_orchestrator():
    service = FakeService(_success_outcome("# ok"))

    response = await crawl_url_impl(
        service,
        url="https://shop.example.com/p/1",
        mode="auto",
        include_images=True,
        force_refresh=False,
        timeout_seconds=60,
    )

    assert response["status"] == "SUCCESS"
    req = service.orchestrator.requests[0]
    assert req.url == "https://shop.example.com/p/1"
    assert req.mode == "auto"
    assert req.timeout_seconds == 60


@pytest.mark.asyncio
async def test_crawl_url_impl_rejects_invalid_mode():
    service = FakeService(_success_outcome("# ok"))
    with pytest.raises(ValueError):
        await crawl_url_impl(
            service,
            url="https://shop.example.com/p/1",
            mode="teleport",
            include_images=True,
            force_refresh=False,
            timeout_seconds=60,
        )


@pytest.mark.asyncio
async def test_crawl_url_impl_clamps_timeout_out_of_range():
    service = FakeService(_success_outcome("# ok"))
    with pytest.raises(ValueError):
        await crawl_url_impl(
            service,
            url="https://shop.example.com/p/1",
            mode="auto",
            include_images=True,
            force_refresh=False,
            timeout_seconds=999,
        )
