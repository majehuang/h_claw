from datetime import datetime, timedelta, timezone

import pytest

from app.storage.database import CrawlResultRecord, DomainRule

pytestmark = pytest.mark.asyncio


def _record(**overrides) -> CrawlResultRecord:
    now = datetime.now(timezone.utc)
    base = dict(
        job_id="cr_test_001",
        cache_key="cache_key_abc",
        source_url="https://shop.example.com/product/1",
        final_url="https://shop.example.com/product/1",
        title="示例商品",
        status="SUCCESS",
        fetch_mode="http",
        markdown_path="/data/results/cr_test_001/content.md",
        content_length=1234,
        status_code=200,
        error_code=None,
        error_message=None,
        created_at=now,
        expires_at=now + timedelta(minutes=15),
    )
    base.update(overrides)
    return CrawlResultRecord(**base)


async def test_upsert_and_get_by_job_id(db):
    await db.upsert_crawl_result(_record())

    fetched = await db.get_by_job_id("cr_test_001")

    assert fetched is not None
    assert fetched.job_id == "cr_test_001"
    assert fetched.title == "示例商品"
    assert fetched.status == "SUCCESS"


async def test_get_by_job_id_returns_none_when_missing(db):
    assert await db.get_by_job_id("does-not-exist") is None


async def test_upsert_updates_existing_record(db):
    await db.upsert_crawl_result(_record(status="RUNNING", title=None))
    await db.upsert_crawl_result(_record(status="SUCCESS", title="示例商品"))

    fetched = await db.get_by_job_id("cr_test_001")
    assert fetched.status == "SUCCESS"
    assert fetched.title == "示例商品"


async def test_get_fresh_by_cache_key_respects_expiry(db):
    now = datetime.now(timezone.utc)
    await db.upsert_crawl_result(
        _record(job_id="cr_expired", expires_at=now - timedelta(seconds=1))
    )
    await db.upsert_crawl_result(
        _record(job_id="cr_fresh", expires_at=now + timedelta(minutes=15))
    )

    fresh = await db.get_fresh_by_cache_key("cache_key_abc", now=now)

    assert fresh is not None
    assert fresh.job_id == "cr_fresh"


async def test_get_fresh_by_cache_key_returns_none_when_all_expired(db):
    now = datetime.now(timezone.utc)
    await db.upsert_crawl_result(
        _record(job_id="cr_expired", expires_at=now - timedelta(seconds=1))
    )

    assert await db.get_fresh_by_cache_key("cache_key_abc", now=now) is None


async def test_domain_rule_upsert_and_get(db):
    rule = DomainRule(
        domain="shop.example.com",
        preferred_mode="stealth",
        min_content_bytes=4096,
        escalate_status_codes=[403, 429],
        source="manual",
    )
    await db.upsert_domain_rule(rule)

    fetched = await db.get_domain_rule("shop.example.com")

    assert fetched.preferred_mode == "stealth"
    assert fetched.min_content_bytes == 4096
    assert fetched.escalate_status_codes == [403, 429]


async def test_get_domain_rule_returns_none_when_absent(db):
    assert await db.get_domain_rule("unknown.example.com") is None


async def test_list_domain_rules_returns_all_sorted(db):
    await db.upsert_domain_rule(DomainRule(domain="b.example.com", preferred_mode="stealth"))
    await db.upsert_domain_rule(DomainRule(domain="a.example.com", preferred_mode="browser"))

    rules = await db.list_domain_rules()

    assert [r.domain for r in rules] == ["a.example.com", "b.example.com"]


async def test_list_domain_rules_empty(db):
    assert await db.list_domain_rules() == []


async def test_delete_domain_rule_removes_and_reports(db):
    await db.upsert_domain_rule(DomainRule(domain="shop.example.com", preferred_mode="stealth"))

    deleted = await db.delete_domain_rule("shop.example.com")

    assert deleted is True
    assert await db.get_domain_rule("shop.example.com") is None


async def test_delete_domain_rule_returns_false_when_absent(db):
    assert await db.delete_domain_rule("missing.example.com") is False


async def test_connect_with_bad_dsn_raises():
    from app.storage.database import Database

    with pytest.raises(OSError):
        await Database.connect(
            "postgresql://nouser:nopass@127.0.0.1:5999/nonexistent", min_size=1, max_size=1
        )
