import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlsplit

from app.crawler.detector import FetchResponse
from app.crawler.http_fetcher import FetchError
from app.security.url_validator import URLValidationError, validate_public_http_url

PoolFetch = Callable[..., Awaitable[Any]]


def _to_browser_cookies(cookies: dict[str, str], url: str) -> list[dict[str, str]]:
    """把 {name: value} 登录 cookie 转成 playwright SetCookieParam。

    域名取目标 URL 的注册域（如 item.jd.com → .jd.com），使登录 cookie 覆盖
    同站各子域。二级域策略对 jd.com / taobao.com 等目标站点足够。
    """
    host = urlsplit(url).hostname or ""
    parts = host.split(".")
    domain = "." + ".".join(parts[-2:]) if len(parts) >= 2 else host
    return [
        {"name": name, "value": value, "domain": domain, "path": "/"}
        for name, value in cookies.items()
    ]


async def fetch_via_browser(
    url: str,
    *,
    pool_fetch: PoolFetch,
    timeout_seconds: int,
    validate: Callable[[str], None],
    extra_kwargs: dict[str, Any] | None = None,
    session: Any = None,
    cookies: dict[str, str] | None = None,
) -> FetchResponse:
    """浏览器/隐身抓取的公共实现：校验初始 URL → 抓取 → 校验最终 URL → 映射。

    浏览器在内部自动跟随重定向，应用层无法逐跳拦截，因此只能校验初始 URL 和
    最终 URL（`resp.url`）。针对重定向中间跳转和子资源的 SSRF 兜底依赖容器
    网络策略（第 14.1 节），这是浏览器层 SSRF 防护的纵深部分。

    `session`（第 14.4 节 / Phase 3a）：传入持久 profile 的浏览器会话时，改用它
    抓取（携带登录态 cookie/指纹），绕过无状态浏览器池；为 None 时走池。
    """
    try:
        await asyncio.to_thread(validate, url)
    except URLValidationError as exc:
        raise FetchError(exc.error_code, str(exc)) from exc

    kwargs: dict[str, Any] = {
        "timeout": timeout_seconds * 1000,
        "network_idle": True,
        "load_dom": True,
        **(extra_kwargs or {}),
    }
    if cookies:
        kwargs["cookies"] = _to_browser_cookies(cookies, url)
    fetch = session.fetch if session is not None else pool_fetch
    response = await fetch(url, **kwargs)

    try:
        await asyncio.to_thread(validate, response.url)
    except URLValidationError as exc:
        raise FetchError(exc.error_code, str(exc)) from exc

    return FetchResponse(
        request_url=url,
        final_url=response.url,
        status_code=response.status,
        html=response.html_content or "",
    )


def resolve_validate(validate: Callable[[str], None] | None) -> Callable[[str], None]:
    return validate if validate is not None else validate_public_http_url
