CREATE TABLE IF NOT EXISTS hermes_crawler.crawl_results (
    job_id TEXT PRIMARY KEY,
    cache_key TEXT NOT NULL,
    source_url TEXT NOT NULL,
    final_url TEXT,
    title TEXT,
    status TEXT NOT NULL,
    fetch_mode TEXT,
    markdown_path TEXT,
    content_length INTEGER,
    status_code INTEGER,
    error_code TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_crawl_cache_key
ON hermes_crawler.crawl_results (cache_key, expires_at);

CREATE TABLE IF NOT EXISTS hermes_crawler.crawl_domain_rules (
    domain TEXT PRIMARY KEY,
    preferred_mode TEXT NOT NULL DEFAULT 'auto',
    min_content_bytes INTEGER NOT NULL DEFAULT 2048,
    escalate_status_codes INTEGER[] NOT NULL DEFAULT '{403,429,503}',
    source TEXT NOT NULL DEFAULT 'manual',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
