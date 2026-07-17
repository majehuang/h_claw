import pytest
from fastmcp import Client

from app.crawler.orchestrator import CrawlOutcome, CrawlRequest
from app.main import mcp, set_service

pytestmark = pytest.mark.asyncio


class FakeOrchestrator:
    def __init__(self, outcome):
        self.outcome = outcome

    async def crawl(self, request: CrawlRequest, session=None):
        return self.outcome


class FakeDB:
    async def get_by_job_id(self, job_id):
        return None


class FakeService:
    def __init__(self, outcome, tmp_path):
        self.orchestrator = FakeOrchestrator(outcome)
        self.db = FakeDB()
        self.data_dir = tmp_path
        self.inline_limit_bytes = 51200
        self.max_markdown_bytes = 2097152


async def test_crawl_url_tool_is_registered_and_callable(tmp_path):
    outcome = CrawlOutcome(
        status="SUCCESS", job_id="cr_x", source_url="https://shop.example.com/p/1",
        final_url="https://shop.example.com/p/1", fetch_mode="http", title="商品",
        markdown="# 商品\n\n价格 199", content_length=16,
        resource_uri="crawl://results/cr_x/content.md",
    )
    set_service(FakeService(outcome, tmp_path))

    async with Client(mcp) as client:
        tools = {t.name for t in await client.list_tools()}
        assert "crawl_url" in tools
        assert "read_crawl_result" in tools

        result = await client.call_tool(
            "crawl_url", {"url": "https://shop.example.com/p/1"}
        )
        assert result.data["status"] == "SUCCESS"
        assert result.data["markdown"] == "# 商品\n\n价格 199"


async def test_crawl_url_tool_description_warns_about_untrusted_content(tmp_path):
    set_service(FakeService(None, tmp_path))
    async with Client(mcp) as client:
        tools = {t.name: t for t in await client.list_tools()}
        description = tools["crawl_url"].description or ""
        assert "不可信" in description
        assert "指令" in description


async def test_read_crawl_result_tool_returns_job_not_found(tmp_path):
    set_service(FakeService(None, tmp_path))
    async with Client(mcp) as client:
        result = await client.call_tool("read_crawl_result", {"job_id": "missing"})
        assert result.data["status"] == "FAILED"
        assert result.data["error_code"] == "JOB_NOT_FOUND"
