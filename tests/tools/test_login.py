import base64
from datetime import datetime, timezone

import pytest

from app.crawler.login_manager import LoginError, LoginSession, LoginState
from app.tools.login import begin_login_impl, cancel_login_impl, poll_login_impl

pytestmark = pytest.mark.asyncio

_T0 = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)


class FakeLoginManager:
    def __init__(self, *, begin=None, begin_error=None, poll=None, cancel=True):
        self._begin = begin
        self._begin_error = begin_error
        self._poll = poll
        self._cancel = cancel
        self.calls = []

    async def begin(self, url):
        self.calls.append(("begin", url))
        if self._begin_error is not None:
            raise self._begin_error
        return self._begin

    async def poll(self, login_id):
        self.calls.append(("poll", login_id))
        return self._poll

    async def cancel(self, login_id):
        self.calls.append(("cancel", login_id))
        return self._cancel


class FakeService:
    def __init__(self, login_manager):
        self.login_manager = login_manager


async def test_begin_login_returns_qr_base64():
    login = LoginSession(
        login_id="lg_1", domain="www.jd.com", status=LoginState.QR_READY,
        qr_png=b"PNGDATA", created_at=_T0, expires_at=_T0,
    )
    service = FakeService(FakeLoginManager(begin=login))

    resp = await begin_login_impl(service, url="https://www.jd.com/login")

    assert resp["login_id"] == "lg_1"
    assert resp["status"] == "QR_READY"
    assert base64.b64decode(resp["qr_png_base64"]) == b"PNGDATA"


async def test_begin_login_maps_login_error():
    service = FakeService(FakeLoginManager(begin_error=LoginError("LOGIN_INIT_FAILED", "无适配器")))

    resp = await begin_login_impl(service, url="https://unknown.com/login")

    assert resp["status"] == "FAILED"
    assert resp["error_code"] == "LOGIN_INIT_FAILED"


async def test_begin_login_when_disabled():
    resp = await begin_login_impl(FakeService(None), url="https://www.jd.com/login")
    assert resp["error_code"] == "LOGIN_INIT_FAILED"


async def test_poll_login_success_returns_session_id():
    login = LoginSession(
        login_id="lg_1", domain="www.jd.com", status=LoginState.SUCCESS,
        session_id="jd-user-001",
    )
    service = FakeService(FakeLoginManager(poll=login))

    resp = await poll_login_impl(service, login_id="lg_1")

    assert resp["status"] == "SUCCESS"
    assert resp["session_id"] == "jd-user-001"
    assert "qr_png_base64" not in resp  # 成功不再回二维码


async def test_poll_login_unknown_returns_not_found():
    service = FakeService(FakeLoginManager(poll=None))

    resp = await poll_login_impl(service, login_id="missing")

    assert resp["status"] == "FAILED"
    assert resp["error_code"] == "LOGIN_NOT_FOUND"


async def test_cancel_login():
    service = FakeService(FakeLoginManager(cancel=True))
    resp = await cancel_login_impl(service, login_id="lg_1")
    assert resp["status"] == "CANCELLED"


async def test_cancel_login_unknown():
    service = FakeService(FakeLoginManager(cancel=False))
    resp = await cancel_login_impl(service, login_id="missing")
    assert resp["status"] == "FAILED"
    assert resp["error_code"] == "LOGIN_NOT_FOUND"
