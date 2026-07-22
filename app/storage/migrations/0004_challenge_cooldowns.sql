-- HC-002：挑战/阻断熔断的持久化冷却态（原为进程内内存，重启即丢）。
-- 只存 domain+session 维度的 next_allowed_at，不存 Cookie/令牌/截图/页面对象。
-- 迁移幂等：可重复执行。
CREATE TABLE IF NOT EXISTS hermes_crawler.challenge_cooldowns (
    domain_key TEXT PRIMARY KEY,           -- "domain|session_id"（无登录态时 session 段为空）
    next_allowed_at TIMESTAMPTZ NOT NULL,  -- 冷却截止：此刻之前相同 domain_key 不再打上游
    reason TEXT,                           -- challenge / blocked / rate_limited（仅供观测）
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_challenge_cooldowns_next_allowed
ON hermes_crawler.challenge_cooldowns (next_allowed_at);
