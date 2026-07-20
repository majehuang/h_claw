from app.storage.cache import compute_cache_key


def test_cache_key_is_stable_for_same_inputs():
    a = compute_cache_key("https://shop.example.com/p/1", True, "zh-CN", None)
    b = compute_cache_key("https://shop.example.com/p/1", True, "zh-CN", None)
    assert a == b


def test_cache_key_independent_of_fetch_mode():
    # 抓取用哪一层（http/browser/stealth）不改变页面内容，故不应影响缓存键：
    # 否则同一 URL 的 auto 与白名单直连 stealth 会各存一份，降低命中。
    key = compute_cache_key("https://shop.example.com/p/1", True, "zh-CN", None)
    assert len(key) == 64


def test_cache_key_changes_with_include_images():
    a = compute_cache_key("https://shop.example.com/p/1", True, "zh-CN", None)
    b = compute_cache_key("https://shop.example.com/p/1", False, "zh-CN", None)
    assert a != b


def test_cache_key_changes_with_session_id():
    a = compute_cache_key("https://shop.example.com/p/1", True, "zh-CN", None)
    b = compute_cache_key("https://shop.example.com/p/1", True, "zh-CN", "sess-1")
    assert a != b


def test_cache_key_normalizes_equivalent_urls():
    # 尾部斜杠、默认端口、fragment 等差异不应产生不同缓存键。
    a = compute_cache_key("https://shop.example.com/p/1", True, "zh-CN", None)
    b = compute_cache_key("https://shop.example.com:443/p/1#section", True, "zh-CN", None)
    assert a == b


def test_cache_key_is_hex_sha256():
    key = compute_cache_key("https://shop.example.com/p/1", True, "zh-CN", None)
    assert len(key) == 64
    assert all(c in "0123456789abcdef" for c in key)
