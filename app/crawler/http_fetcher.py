import asyncio
from collections.abc import Callable
from urllib.parse import urljoin

from curl_cffi.const import CurlECode
from curl_cffi.requests import RequestsError
from scrapling.fetchers import AsyncFetcher

from app.crawler.detector import FetchResponse
from app.security.url_validator import URLValidationError, validate_public_http_url

_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


class FetchError(Exception):
    def __init__(self, error_code: str, message: str):
        self.error_code = error_code
        super().__init__(message)


async def fetch_http(
    url: str,
    *,
    timeout_seconds: int = 15,
    max_redirects: int = 5,
    retries: int = 1,
    validate: Callable[[str], None] = validate_public_http_url,
) -> FetchResponse:
    """按第 14.1 节要求，每次重定向后都重新校验目标 URL，而不是信任
    底层 HTTP 客户端内置的自动跟随重定向（那样只会校验最初的 URL，
    给"重定向到内网地址"的 SSRF 变种留下空子）。
    """
    current_url = url

    for _ in range(max_redirects + 1):
        try:
            await asyncio.to_thread(validate, current_url)
        except URLValidationError as exc:
            raise FetchError(exc.error_code, str(exc)) from exc

        try:
            response = await AsyncFetcher.get(
                current_url,
                timeout=timeout_seconds,
                follow_redirects=False,
                retries=retries,
                stealthy_headers=True,
            )
        except RequestsError as exc:
            if exc.code == CurlECode.OPERATION_TIMEDOUT:
                raise FetchError("FETCH_TIMEOUT", str(exc)) from exc
            raise FetchError("UPSTREAM_BLOCKED", str(exc)) from exc

        if response.status in _REDIRECT_STATUSES:
            location = response.headers.get("location")
            if not location:
                raise FetchError("UPSTREAM_BLOCKED", "重定向响应缺少 Location 头")
            current_url = urljoin(current_url, location)
            continue

        return FetchResponse(
            request_url=url,
            final_url=response.url,
            status_code=response.status,
            html=response.html_content or "",
        )

    raise FetchError("UPSTREAM_BLOCKED", f"超过最大重定向次数限制: {max_redirects}")
