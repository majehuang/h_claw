-- Phase 3a：持久化浏览器 Profile 元数据（cookie/指纹密文在 /data/profiles/*.enc，库中不存明文）。
CREATE TABLE IF NOT EXISTS hermes_crawler.account_profiles (
    session_id TEXT PRIMARY KEY,
    domain TEXT NOT NULL,
    label TEXT,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    fingerprint_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_account_profiles_domain
ON hermes_crawler.account_profiles (domain);
