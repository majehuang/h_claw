import hashlib
from urllib.parse import urlsplit, urlunsplit

_DEFAULT_PORTS = {"http": "80", "https": "443"}


def _canonicalize_url(url: str) -> str:
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    hostname = (parts.hostname or "").lower()

    netloc = hostname
    if parts.port is not None and str(parts.port) != _DEFAULT_PORTS.get(scheme):
        netloc = f"{hostname}:{parts.port}"

    path = parts.path or "/"
    # 去掉 fragment，保留 query（query 可能影响商品页内容）。
    return urlunsplit((scheme, netloc, path, parts.query, ""))


def compute_cache_key(
    url: str,
    include_images: bool,
    locale: str | None,
    session_id: str | None,
) -> str:
    """按第 12 节生成缓存键：
    SHA256(canonical_url + include_images + locale + session_id)。

    抓取层级（http/browser/stealth）不影响页面内容，故不纳入缓存键——否则同一
    URL 在 auto 与白名单直连 stealth 之间会各存一份，降低命中率。
    """
    canonical_url = _canonicalize_url(url)
    material = "\n".join(
        [
            canonical_url,
            "1" if include_images else "0",
            locale or "",
            session_id or "",
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
