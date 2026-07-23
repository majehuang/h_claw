from datetime import datetime, timedelta, timezone

import pytest

from app.crawler.login_manager import LoginManager, LoginState

pytestmark = pytest.mark.asyncio

_T0 = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)


class FakeAdapter:
    domain_patterns = ("jd.com",)

    def __init__(self, statuses=None):
        self._statuses = list(statuses or [])
        self.opened_url = None

    async def open_login(self, session, url):
        self.opened_url = url

    async def capture_qr(self, session):
        return b"PNGDATA"

    async def poll_status(self, session):
        return self._statuses.pop(0) if self._statuses else "PENDING"


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


def _manager(adapter, *, clock=None, ttl=180):
    opened, closed = [], []

    async def opener(domain):
        handle = object()
        opened.append((domain, handle))
        return handle

    async def closer(handle, *, success, domain=None):
        closed.append((handle, success))
        return "new-session-id" if success else None

    mgr = LoginManager(
        adapters=[adapter],
        session_opener=opener,
        session_closer=closer,
        clock=clock or Clock(_T0),
        id_factory=lambda: "lg_test",
        ttl_seconds=ttl,
    )
    return mgr, opened, closed


async def test_begin_opens_login_and_returns_qr():
    adapter = FakeAdapter()
    mgr, opened, _ = _manager(adapter)

    login = await mgr.begin("https://www.jd.com/login")

    assert login.login_id == "lg_test"
    assert login.status == LoginState.QR_READY
    assert login.qr_png == b"PNGDATA"
    assert adapter.opened_url == "https://www.jd.com/login"
    assert opened[0][0] == "www.jd.com"


async def test_poll_failed_closes_without_sealing_profile():
    # HC-011：适配器判定登录落到非允许域名 → FAILED，关闭上下文且不封存 profile。
    mgr, _, closed = _manager(FakeAdapter(statuses=["FAILED"]))
    login = await mgr.begin("https://www.jd.com/login")

    result = await mgr.poll(login.login_id)

    assert result.status == LoginState.FAILED
    assert result.session_id is None            # 未封存 profile
    assert closed == [(closed[0][0], False)]    # closer 以 success=False 关闭上下文


async def test_poll_pending_stays_qr_ready():
    mgr, _, _ = _manager(FakeAdapter(statuses=["PENDING"]))
    await mgr.begin("https://www.jd.com/login")

    login = await mgr.poll("lg_test")
    assert login.status == LoginState.QR_READY


async def test_poll_scanned():
    mgr, _, _ = _manager(FakeAdapter(statuses=["SCANNED"]))
    await mgr.begin("https://www.jd.com/login")

    assert (await mgr.poll("lg_test")).status == LoginState.SCANNED


async def test_poll_success_seals_and_returns_session_id():
    mgr, _, closed = _manager(FakeAdapter(statuses=["SUCCESS"]))
    await mgr.begin("https://www.jd.com/login")

    login = await mgr.poll("lg_test")

    assert login.status == LoginState.SUCCESS
    assert login.session_id == "new-session-id"
    assert closed == [(closed[0][0], True)]        # 成功回写密文
    assert await mgr.poll("lg_test") is None        # 完成后移出注册表


async def test_poll_expires_after_ttl():
    clock = Clock(_T0)
    mgr, _, closed = _manager(FakeAdapter(statuses=["PENDING"]), clock=clock, ttl=180)
    await mgr.begin("https://www.jd.com/login")

    clock.now = _T0 + timedelta(seconds=181)
    login = await mgr.poll("lg_test")

    assert login.status == LoginState.EXPIRED
    assert closed == [(closed[0][0], False)]        # 过期释放且不落盘
    assert await mgr.poll("lg_test") is None


async def test_cancel_closes_and_returns_true():
    mgr, _, closed = _manager(FakeAdapter())
    await mgr.begin("https://www.jd.com/login")

    assert await mgr.cancel("lg_test") is True
    assert closed == [(closed[0][0], False)]
    assert await mgr.poll("lg_test") is None


async def test_cancel_unknown_returns_false():
    mgr, _, _ = _manager(FakeAdapter())
    assert await mgr.cancel("nope") is False


async def test_poll_unknown_returns_none():
    mgr, _, _ = _manager(FakeAdapter())
    assert await mgr.poll("nope") is None


async def test_get_qr_png_returns_bytes_for_active_session():
    mgr, _, _ = _manager(FakeAdapter())
    await mgr.begin("https://www.jd.com/login")

    assert mgr.get_qr_png("lg_test") == b"PNGDATA"


async def test_get_qr_png_returns_none_for_unknown_id():
    mgr, _, _ = _manager(FakeAdapter())
    assert mgr.get_qr_png("nope") is None


async def test_get_qr_png_returns_none_after_cancel():
    mgr, _, _ = _manager(FakeAdapter())
    await mgr.begin("https://www.jd.com/login")
    await mgr.cancel("lg_test")

    assert mgr.get_qr_png("lg_test") is None


async def test_get_qr_entry_returns_session_with_domain_and_png():
    mgr, _, _ = _manager(FakeAdapter())
    await mgr.begin("https://www.jd.com/login")

    entry = mgr.get_qr_entry("lg_test")

    assert entry.login_id == "lg_test"
    assert entry.domain == "www.jd.com"
    assert entry.qr_png == b"PNGDATA"


async def test_get_qr_entry_returns_none_for_unknown_id():
    mgr, _, _ = _manager(FakeAdapter())
    assert mgr.get_qr_entry("nope") is None
