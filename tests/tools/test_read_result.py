from datetime import datetime, timezone

import pytest

from app.storage.database import CrawlResultRecord
from app.storage.results import write_result
from app.tools.read_result import read_result_impl

pytestmark = pytest.mark.asyncio


def _record(job_id, status="SUCCESS", markdown_path=None, error_code=None, error_message=None):
    now = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)
    return CrawlResultRecord(
        job_id=job_id, cache_key="k", source_url="https://shop.example.com/p/1",
        final_url="https://shop.example.com/p/1", title="商品", status=status,
        fetch_mode="http", markdown_path=markdown_path, content_length=None,
        status_code=200, error_code=error_code, error_message=error_message,
        created_at=now, expires_at=now,
    )


class FakeDB:
    def __init__(self, record=None):
        self._record = record

    async def get_by_job_id(self, job_id):
        if self._record and self._record.job_id == job_id:
            return self._record
        return None


class FakeService:
    def __init__(self, db, data_dir):
        self.db = db
        self.data_dir = data_dir


async def test_reads_and_paginates_markdown(tmp_path):
    write_result(tmp_path, "cr_1", "0123456789", {"job_id": "cr_1"})
    paths = tmp_path / "results" / "cr_1" / "content.md"
    service = FakeService(FakeDB(_record("cr_1", markdown_path=str(paths))), tmp_path)

    first = await read_result_impl(service, job_id="cr_1", offset=0, max_chars=4)
    assert first["markdown"] == "0123"
    assert first["next_offset"] == 4
    assert first["has_more"] is True
    assert first["status"] == "SUCCESS"

    second = await read_result_impl(service, job_id="cr_1", offset=4, max_chars=100)
    assert second["markdown"] == "456789"
    assert second["has_more"] is False


async def test_missing_job_returns_job_not_found(tmp_path):
    service = FakeService(FakeDB(None), tmp_path)

    response = await read_result_impl(service, job_id="nope", offset=0, max_chars=100)

    assert response["status"] == "FAILED"
    assert response["error_code"] == "JOB_NOT_FOUND"


async def test_failed_job_returns_stored_error_not_file(tmp_path):
    record = _record(
        "cr_blocked", status="BLOCKED", markdown_path=None,
        error_code="UPSTREAM_BLOCKED", error_message="全部层级被拦截",
    )
    service = FakeService(FakeDB(record), tmp_path)

    response = await read_result_impl(service, job_id="cr_blocked", offset=0, max_chars=100)

    assert response["status"] == "BLOCKED"
    assert response["error_code"] == "UPSTREAM_BLOCKED"
    assert response["error_message"] == "全部层级被拦截"
    assert "markdown" not in response


async def test_success_but_missing_file_returns_error(tmp_path):
    service = FakeService(
        FakeDB(_record("cr_gone", markdown_path=str(tmp_path / "results/cr_gone/content.md"))),
        tmp_path,
    )

    response = await read_result_impl(service, job_id="cr_gone", offset=0, max_chars=100)

    assert response["status"] == "FAILED"
    assert response["error_code"] == "INTERNAL_ERROR"
