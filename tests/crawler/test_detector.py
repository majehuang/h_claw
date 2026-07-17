from app.crawler.detector import DomainRuleDefaults, FetchResponse, detect

URL = "https://shop.example.com/product/123"


def _response(**overrides) -> FetchResponse:
    base = dict(
        request_url=URL,
        final_url=URL,
        status_code=200,
        html="<html><head><title>正常商品页</title></head>"
        "<body><p>" + ("商品详情正文内容，价格 ¥199。" * 60) + "</p></body></html>",
    )
    base.update(overrides)
    return FetchResponse(**base)


def test_usable_page_is_ok():
    result = detect(_response())
    assert result.ok is True
    assert result.reason == "ok"


def test_blocked_status_takes_priority_over_everything():
    result = detect(_response(status_code=403, html="<html>请完成安全验证</html>"))
    assert result.ok is False
    assert result.reason == "blocked_status"


def test_login_redirect_detected():
    result = detect(_response(final_url="https://shop.example.com/login?next=/product/123"))
    assert result.ok is False
    assert result.reason == "login_redirect"


def test_captcha_redirect_detected():
    result = detect(_response(final_url="https://challenges.cloudflare.com/turnstile"))
    assert result.ok is False
    assert result.reason == "captcha_redirect"


def test_captcha_keyword_detected():
    result = detect(_response(html="<html><body>Please verify you are human</body></html>"))
    assert result.ok is False
    assert result.reason == "captcha_detected"


def test_captcha_selector_detected():
    result = detect(
        _response(html='<html><body><div class="g-recaptcha"></div></body></html>')
    )
    assert result.ok is False
    assert result.reason == "captcha_detected"


def test_spa_shell_detected_before_short_content():
    # 空壳页面同时满足"正文过短"和"SPA 根节点"两个条件，
    # 应该优先归类为更具体的 spa_shell，而不是笼统的 short_content。
    result = detect(_response(html='<html><body><div id="app"></div></body></html>'))
    assert result.ok is False
    assert result.reason == "spa_shell"


def test_short_content_detected_when_no_spa_root():
    rule = DomainRuleDefaults(min_content_bytes=200)
    result = detect(_response(html="<html><body><p>太短了</p></body></html>"), rule=rule)
    assert result.ok is False
    assert result.reason == "short_content"


def test_no_structured_signal_detected():
    long_text = "这是一段没有标题没有价格没有结构化数据的普通段落文字。" * 30
    result = detect(_response(html=f"<html><body><p>{long_text}</p></body></html>"))
    assert result.ok is False
    assert result.reason == "no_structured_signal"


def test_url_mismatch_detected():
    result = detect(_response(final_url="https://totally-different-site.com/somewhere"))
    assert result.ok is False
    assert result.reason == "url_mismatch"


def test_same_site_redirect_is_not_url_mismatch():
    result = detect(_response(final_url="https://m.shop.example.com/product/123"))
    assert result.ok is True
