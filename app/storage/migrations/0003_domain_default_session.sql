-- Phase 3a / A4：白名单域名可默认关联一个登录 profile（session_id），
-- mode=auto 时自动带登录态抓取。
ALTER TABLE hermes_crawler.crawl_domain_rules
ADD COLUMN IF NOT EXISTS default_session_id TEXT;
