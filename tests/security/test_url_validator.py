import pytest

from app.security.url_validator import URLValidationError, validate_public_http_url


def resolver_for(ips: list[str]):
    def _resolve(hostname: str) -> list[str]:
        return ips
    return _resolve


def test_accepts_public_https_url():
    result = validate_public_http_url(
        "https://shop.example.com/product/123",
        resolver=resolver_for(["93.184.216.34"]),
    )
    assert result.hostname == "shop.example.com"
    assert result.resolved_ips == ("93.184.216.34",)


@pytest.mark.parametrize("scheme_url", [
    "ftp://shop.example.com/product",
    "file:///etc/passwd",
    "gopher://shop.example.com/",
    "javascript:alert(1)",
])
def test_rejects_disallowed_schemes(scheme_url):
    with pytest.raises(URLValidationError) as exc_info:
        validate_public_http_url(scheme_url, resolver=resolver_for(["93.184.216.34"]))
    assert exc_info.value.error_code == "INVALID_URL"


def test_rejects_url_with_userinfo():
    with pytest.raises(URLValidationError) as exc_info:
        validate_public_http_url(
            "https://user:password@shop.example.com/product",
            resolver=resolver_for(["93.184.216.34"]),
        )
    assert exc_info.value.error_code == "INVALID_URL"


def test_rejects_when_dns_resolves_nothing():
    with pytest.raises(URLValidationError) as exc_info:
        validate_public_http_url("https://nowhere.example.com/", resolver=resolver_for([]))
    assert exc_info.value.error_code == "INVALID_URL"


@pytest.mark.parametrize("blocked_ip", [
    "127.0.0.1",           # loopback
    "10.1.2.3",             # RFC1918
    "172.16.5.5",           # RFC1918
    "192.168.1.1",          # RFC1918
    "169.254.1.1",          # link-local
    "169.254.169.254",      # cloud metadata
    "::1",                   # IPv6 loopback
    "fc00::1",               # IPv6 unique local
    "fe80::1",               # IPv6 link-local
])
def test_blocks_private_and_metadata_ips(blocked_ip):
    with pytest.raises(URLValidationError) as exc_info:
        validate_public_http_url(
            "https://shop.example.com/product",
            resolver=resolver_for([blocked_ip]),
        )
    assert exc_info.value.error_code == "SSRF_BLOCKED"


def test_blocks_when_any_resolved_ip_is_private():
    # DNS 返回多个 IP 时必须逐一校验，命中任意一个私网地址即拒绝。
    with pytest.raises(URLValidationError) as exc_info:
        validate_public_http_url(
            "https://shop.example.com/product",
            resolver=resolver_for(["93.184.216.34", "10.0.0.5"]),
        )
    assert exc_info.value.error_code == "SSRF_BLOCKED"


def test_rejects_missing_hostname():
    with pytest.raises(URLValidationError) as exc_info:
        validate_public_http_url("https:///product", resolver=resolver_for(["93.184.216.34"]))
    assert exc_info.value.error_code == "INVALID_URL"
