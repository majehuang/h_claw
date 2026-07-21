from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import asyncpg

_SCHEMA = "hermes_crawler"
_MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_CRAWL_RESULT_COLUMNS = (
    "job_id",
    "cache_key",
    "source_url",
    "final_url",
    "title",
    "status",
    "fetch_mode",
    "markdown_path",
    "content_length",
    "status_code",
    "error_code",
    "error_message",
    "created_at",
    "expires_at",
)


@dataclass(frozen=True)
class CrawlResultRecord:
    job_id: str
    cache_key: str
    source_url: str
    final_url: str | None
    title: str | None
    status: str
    fetch_mode: str | None
    markdown_path: str | None
    content_length: int | None
    status_code: int | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class DomainRule:
    domain: str
    preferred_mode: str = "auto"
    min_content_bytes: int = 2048
    escalate_status_codes: list[int] | None = None
    source: str = "manual"
    default_session_id: str | None = None


@dataclass(frozen=True)
class AccountProfile:
    session_id: str
    domain: str
    label: str | None
    status: str
    fingerprint_id: str | None
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None


_ACCOUNT_PROFILE_COLUMNS = (
    "session_id",
    "domain",
    "label",
    "status",
    "fingerprint_id",
    "created_at",
    "last_used_at",
    "expires_at",
)


def _row_to_result(row: asyncpg.Record) -> CrawlResultRecord:
    return CrawlResultRecord(**{col: row[col] for col in _CRAWL_RESULT_COLUMNS})


def _row_to_profile(row: asyncpg.Record) -> AccountProfile:
    return AccountProfile(**{col: row[col] for col in _ACCOUNT_PROFILE_COLUMNS})


def _row_to_domain_rule(row: asyncpg.Record) -> DomainRule:
    return DomainRule(
        domain=row["domain"],
        preferred_mode=row["preferred_mode"],
        min_content_bytes=row["min_content_bytes"],
        escalate_status_codes=list(row["escalate_status_codes"]),
        source=row["source"],
        default_session_id=row["default_session_id"],
    )


class Database:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str, *, min_size: int = 1, max_size: int = 5) -> "Database":
        pool = await asyncpg.create_pool(dsn, min_size=min_size, max_size=max_size)
        return cls(pool)

    async def close(self) -> None:
        await self._pool.close()

    async def apply_migrations(self) -> None:
        for path in sorted(_MIGRATIONS_DIR.glob("*.sql")):
            sql = path.read_text(encoding="utf-8")
            async with self._pool.acquire() as conn:
                await conn.execute(sql)

    async def truncate_all(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                f"TRUNCATE {_SCHEMA}.crawl_results, {_SCHEMA}.crawl_domain_rules, "
                f"{_SCHEMA}.account_profiles"
            )

    async def upsert_crawl_result(self, record: CrawlResultRecord) -> None:
        columns = _CRAWL_RESULT_COLUMNS
        placeholders = ", ".join(f"${i}" for i in range(1, len(columns) + 1))
        update_clause = ", ".join(
            f"{col} = EXCLUDED.{col}" for col in columns if col != "job_id"
        )
        values = [getattr(record, col) for col in columns]

        async with self._pool.acquire() as conn:
            await conn.execute(
                f"""
                INSERT INTO {_SCHEMA}.crawl_results ({", ".join(columns)})
                VALUES ({placeholders})
                ON CONFLICT (job_id) DO UPDATE SET {update_clause}
                """,
                *values,
            )

    async def get_by_job_id(self, job_id: str) -> CrawlResultRecord | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT * FROM {_SCHEMA}.crawl_results WHERE job_id = $1", job_id
            )
        return _row_to_result(row) if row else None

    async def get_fresh_by_cache_key(
        self, cache_key: str, now: datetime
    ) -> CrawlResultRecord | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT * FROM {_SCHEMA}.crawl_results
                WHERE cache_key = $1 AND expires_at > $2
                ORDER BY created_at DESC
                LIMIT 1
                """,
                cache_key,
                now,
            )
        return _row_to_result(row) if row else None

    async def get_domain_rule(self, domain: str) -> DomainRule | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT * FROM {_SCHEMA}.crawl_domain_rules WHERE domain = $1", domain
            )
        return _row_to_domain_rule(row) if row else None

    async def list_domain_rules(self) -> list[DomainRule]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT * FROM {_SCHEMA}.crawl_domain_rules ORDER BY domain"
            )
        return [_row_to_domain_rule(row) for row in rows]

    async def delete_domain_rule(self, domain: str) -> bool:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"DELETE FROM {_SCHEMA}.crawl_domain_rules "
                f"WHERE domain = $1 RETURNING domain",
                domain,
            )
        return row is not None

    async def upsert_domain_rule(self, rule: DomainRule) -> None:
        escalate_status_codes = rule.escalate_status_codes or [403, 429, 503]
        async with self._pool.acquire() as conn:
            await conn.execute(
                f"""
                INSERT INTO {_SCHEMA}.crawl_domain_rules (
                    domain, preferred_mode, min_content_bytes,
                    escalate_status_codes, source, default_session_id, updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6, now())
                ON CONFLICT (domain) DO UPDATE SET
                    preferred_mode = EXCLUDED.preferred_mode,
                    min_content_bytes = EXCLUDED.min_content_bytes,
                    escalate_status_codes = EXCLUDED.escalate_status_codes,
                    source = EXCLUDED.source,
                    default_session_id = EXCLUDED.default_session_id,
                    updated_at = now()
                """,
                rule.domain,
                rule.preferred_mode,
                rule.min_content_bytes,
                escalate_status_codes,
                rule.source,
                rule.default_session_id,
            )

    async def upsert_profile(self, profile: AccountProfile) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                f"""
                INSERT INTO {_SCHEMA}.account_profiles (
                    session_id, domain, label, status, fingerprint_id,
                    created_at, last_used_at, expires_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (session_id) DO UPDATE SET
                    domain = EXCLUDED.domain,
                    label = EXCLUDED.label,
                    status = EXCLUDED.status,
                    fingerprint_id = EXCLUDED.fingerprint_id,
                    last_used_at = EXCLUDED.last_used_at,
                    expires_at = EXCLUDED.expires_at
                """,
                profile.session_id,
                profile.domain,
                profile.label,
                profile.status,
                profile.fingerprint_id,
                profile.created_at,
                profile.last_used_at,
                profile.expires_at,
            )

    async def get_profile(self, session_id: str) -> AccountProfile | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT * FROM {_SCHEMA}.account_profiles WHERE session_id = $1",
                session_id,
            )
        return _row_to_profile(row) if row else None

    async def list_profiles(self) -> list[AccountProfile]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT * FROM {_SCHEMA}.account_profiles ORDER BY session_id"
            )
        return [_row_to_profile(row) for row in rows]

    async def revoke_profile(self, session_id: str) -> bool:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"UPDATE {_SCHEMA}.account_profiles SET status = 'REVOKED' "
                f"WHERE session_id = $1 RETURNING session_id",
                session_id,
            )
        return row is not None

    async def touch_profile_last_used(
        self, session_id: str, now: datetime
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                f"UPDATE {_SCHEMA}.account_profiles SET last_used_at = $2 "
                f"WHERE session_id = $1",
                session_id,
                now,
            )
