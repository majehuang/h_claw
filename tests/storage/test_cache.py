from app.storage.cache import compute_cache_key


def test_cache_key_is_stable_for_same_inputs():
    a = compute_cache_key("https://shop.example.com/p/1", "auto", True, "zh-CN", None)
    b = compute_cache_key("https://shop.example.com/p/1", "auto", True, "zh-CN", None)
    assert a == b


def test_cache_key_changes_with_mode():
    a = compute_cache_key("https://shop.example.com/p/1", "auto", True, "zh-CN", None)
    b = compute_cache_key("https://shop.example.com/p/1", "browser", True, "zh-CN", None)
    assert a != b


def test_cache_key_changes_with_include_images():
    a = compute_cache_key("https://shop.example.com/p/1", "auto", True, "zh-CN", None)
    b = compute_cache_key("https://shop.example.com/p/1", "auto", False, "zh-CN", None)
    assert a != b


def test_cache_key_changes_with_session_id():
    a = compute_cache_key("https://shop.example.com/p/1", "auto", True, "zh-CN", None)
    b = compute_cache_key("https://shop.example.com/p/1", "auto", True, "zh-CN", "sess-1")
    assert a != b


def test_cache_key_normalizes_equivalent_urls():
    # 尾部斜杠、默认端口、fragment 等差异不应产生不同缓存键。
    a = compute_cache_key("https://shop.example.com/p/1", "auto", True, "zh-CN", None)
    b = compute_cache_key("https://shop.example.com:443/p/1#section", "auto", True, "zh-CN", None)
    assert a == b


def test_cache_key_is_hex_sha256():
    key = compute_cache_key("https://shop.example.com/p/1", "auto", True, "zh-CN", None)
    assert len(key) == 64
    assert all(c in "0123456789abcdef" for c in key)
