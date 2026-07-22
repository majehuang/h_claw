"""HC-005：挑战检测证据标准化 + 站点适配器隔离（UT-006~UT-011）。

断言检测结果携带 provider / reason / matched_signal，且证据只含短 token，
不含完整 HTML / Cookie / PII；站点专属特征只在其域名下生效。
"""
from app.crawler.detector import (
    INTERACTIVE_CHALLENGE_REASONS,
    DomainRuleDefaults,
    FetchResponse,
    detect,
)

RULE = DomainRuleDefaults()

GOOD_HTML = (
    "<html><head><title>示例商品</title></head><body><p>"
    + ("商品详情正文，价格 ¥199，规格颜色尺码库存俱全。" * 40)
    + '</p><script type="application/ld+json">{"@type":"Product","name":"x"}</script>'
    + "</body></html>"
)


def _resp(html=GOOD_HTML, url="https://shop.example.com/p/1", final=None, status=200):
    return FetchResponse(
        request_url=url, final_url=final or url, status_code=status, html=html
    )


# --- UT-006 关键词检测 ---
def test_keyword_challenge_has_provider_and_signal():
    r = detect(_resp(html="<html><body>请完成安全验证</body></html>"), RULE)
    assert r.ok is False
    assert r.reason == "captcha_detected"
    assert r.provider == "generic"
    assert r.matched_signal == "keyword=请完成安全验证"
    assert r.is_interactive_challenge is True


def test_evidence_signal_excludes_full_html():
    long_html = "<html><body>请完成安全验证" + ("X" * 5000) + "</body></html>"
    r = detect(_resp(html=long_html), RULE)
    # matched_signal 只保留短 token，绝不回带整页 HTML。
    assert len(r.matched_signal) < 60
    assert "X" * 100 not in r.matched_signal


# --- UT-007 选择器检测 + provider 归类 ---
def test_selector_challenge_maps_provider_cloudflare():
    html = "<html><body><div id='cf-challenge-stage'></div></body></html>"
    r = detect(_resp(html=html), RULE)
    assert r.reason == "captcha_detected"
    assert r.provider == "cloudflare"
    assert r.matched_signal == "selector=#cf-challenge-stage"


def test_selector_challenge_maps_provider_recaptcha():
    html = "<html><body><div class='g-recaptcha'></div></body></html>"
    r = detect(_resp(html=html), RULE)
    assert r.provider == "recaptcha"


# --- UT-008 挑战域名重定向 ---
def test_captcha_domain_redirect():
    r = detect(
        _resp(final="https://challenges.cloudflare.com/turnstile", html="<html></html>"),
        RULE,
    )
    assert r.reason == "captcha_redirect"
    assert r.provider == "cloudflare"
    assert r.is_interactive_challenge is True


def test_datadome_domain_redirect_provider():
    r = detect(
        _resp(final="https://geo.captcha-delivery.com/c", html="<html></html>"), RULE
    )
    assert r.provider == "datadome"


# --- UT-009 正常商品页不误判 ---
def test_normal_product_page_passes():
    r = detect(_resp(), RULE)
    assert r.ok is True
    assert r.is_interactive_challenge is False


# --- UT-010 登录页与挑战页区分 ---
def test_login_page_is_login_not_captcha():
    r = detect(_resp(final="https://shop.example.com/login", html="<html></html>"), RULE)
    assert r.reason == "login_redirect"
    assert r.reason not in INTERACTIVE_CHALLENGE_REASONS


def test_captcha_page_is_captcha_not_login():
    r = detect(_resp(html="<html><body>验证您是真人</body></html>"), RULE)
    assert r.reason == "captcha_detected"


# --- UT-011 站点适配器隔离 ---
def test_site_adapter_signal_matches_only_on_its_domain():
    # 淘宝滑块容器出现在淘宝域名 → 命中站点适配器。
    html = "<html><body><div id='nc_1_wrapper'></div></body></html>"
    r = detect(_resp(url="https://item.taobao.com/i", final="https://item.taobao.com/i",
                     html=html), RULE)
    assert r.reason == "captcha_detected"
    assert r.provider == "taobao-slider"


def test_site_adapter_signal_ignored_on_other_domain():
    # 同样的淘宝滑块特征出现在非淘宝域名 → 不应用淘宝专用规则；页面本身内容充足则通过。
    html = (
        "<html><head><title>正常页</title></head><body>"
        "<div id='nc_1_wrapper'></div><p>"
        + ("正常商品正文内容，颜色尺码价格 ¥88。" * 40)
        + "</p></body></html>"
    )
    r = detect(_resp(url="https://shop.example.com/p", final="https://shop.example.com/p",
                     html=html), RULE)
    assert r.ok is True


def test_generic_rule_still_works_on_other_domain():
    # 站点隔离不影响通用规则：通用关键词在任意域名仍然命中。
    r = detect(_resp(url="https://shop.example.com/p", html="<html><body>access denied</body></html>"),
               RULE)
    assert r.reason == "captcha_detected"
    assert r.provider == "generic"
