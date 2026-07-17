import pytest

from app.crawler.http_fetcher import FetchError, fetch_http

pytestmark = pytest.mark.asyncio


def _no_op_validate(url: str) -> None:
    """本地测试服务器跑在 127.0.0.1，真实 SSRF 校验会直接拒绝，
    这里用一个记录调用次数的桩替代，验证"每跳都重新校验"的行为。
    """
    return None


class _RecordingValidator:
    def __init__(self):
        self.calls: list[str] = []

    def __call__(self, url: str) -> None:
        self.calls.append(url)


async def test_fetches_simple_page(local_server):
    result = await fetch_http(f"{local_server}/ok", validate=_no_op_validate)

    assert result.status_code == 200
    assert result.final_url == f"{local_server}/ok"
    assert "hello" in result.html


async def test_follows_single_redirect_and_returns_final_url(local_server):
    result = await fetch_http(f"{local_server}/redirect-once", validate=_no_op_validate)

    assert result.status_code == 200
    assert result.final_url == f"{local_server}/ok"
    assert result.request_url == f"{local_server}/redirect-once"


async def test_revalidates_url_on_every_redirect_hop(local_server):
    validator = _RecordingValidator()

    await fetch_http(f"{local_server}/redirect-chain/2", validate=validator)

    # 起始 URL + /redirect-chain/2 -> /redirect-chain/1 -> /redirect-chain/0 -> /ok
    # 每一跳都应该被重新校验，而不是只校验最初的 URL。
    assert len(validator.calls) == 4
    assert validator.calls[0] == f"{local_server}/redirect-chain/2"
    assert validator.calls[-1] == f"{local_server}/ok"


async def test_raises_upstream_blocked_when_redirect_loop_exceeds_max_redirects(local_server):
    with pytest.raises(FetchError) as exc_info:
        await fetch_http(
            f"{local_server}/redirect-loop", validate=_no_op_validate, max_redirects=3
        )
    assert exc_info.value.error_code == "UPSTREAM_BLOCKED"


async def test_returns_status_code_for_non_redirect_error_responses(local_server):
    result = await fetch_http(f"{local_server}/forbidden", validate=_no_op_validate)
    assert result.status_code == 403


async def test_validation_failure_is_translated_to_fetch_error(local_server):
    def _always_reject(url: str) -> None:
        from app.security.url_validator import URLValidationError

        raise URLValidationError("SSRF_BLOCKED", "禁止访问")

    with pytest.raises(FetchError) as exc_info:
        await fetch_http(f"{local_server}/ok", validate=_always_reject)
    assert exc_info.value.error_code == "SSRF_BLOCKED"
