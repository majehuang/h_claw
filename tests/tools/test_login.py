import base64
import contextlib
from datetime import datetime, timezone

import pytest

import app.tools.login as login_module
from app.crawler.login_manager import LoginError, LoginSession, LoginState
from app.tools.login import (
    begin_login_impl,
    cancel_login_impl,
    poll_login_impl,
    render_qr_terminal_impl,
)

pytestmark = pytest.mark.asyncio

_T0 = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)


class FakeLoginManager:
    def __init__(
        self, *, begin=None, begin_error=None, poll=None, cancel=True, qr_entry=None
    ):
        self._begin = begin
        self._begin_error = begin_error
        self._poll = poll
        self._cancel = cancel
        self._qr_entry = qr_entry
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

    def get_qr_entry(self, login_id):
        self.calls.append(("get_qr_entry", login_id))
        return self._qr_entry


@contextlib.contextmanager
def _patched_qr_render(*, decode=None, decode_error=None, render=lambda payload: f"ASCII[{payload}]"):
    original_decode = login_module.decode_qr_payload
    original_render = login_module.render_ascii_qr

    def fake_decode(png_bytes):
        if decode_error is not None:
            raise decode_error
        return decode

    login_module.decode_qr_payload = fake_decode
    login_module.render_ascii_qr = render
    try:
        yield
    finally:
        login_module.decode_qr_payload = original_decode
        login_module.render_ascii_qr = original_render


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


async def test_render_qr_terminal_returns_ascii_qr():
    login = LoginSession(
        login_id="lg_1", domain="item.jd.com", status=LoginState.QR_READY,
        qr_png=b"PNGBYTES",
    )
    service = FakeService(FakeLoginManager(qr_entry=login))

    with _patched_qr_render(decode="https://qr.m.jd.com/p?k=abc"):
        resp = await render_qr_terminal_impl(service, login_id="lg_1")

    assert resp["status"] == "SUCCESS"
    assert resp["ascii_qr"] == "ASCII[https://qr.m.jd.com/p?k=abc]"
    assert "domain_mismatch" not in resp


async def test_render_qr_terminal_flags_domain_mismatch():
    login = LoginSession(
        login_id="lg_1", domain="item.jd.com", status=LoginState.QR_READY,
        qr_png=b"PNGBYTES",
    )
    service = FakeService(FakeLoginManager(qr_entry=login))

    with _patched_qr_render(decode="https://www.xiaohongshu.com/discovery?x=1"):
        resp = await render_qr_terminal_impl(service, login_id="lg_1")

    assert resp["status"] == "SUCCESS"
    assert resp["domain_mismatch"] is True
    assert "warning" in resp
    assert "ascii_qr" in resp  # 仍然返回，交给调用方自行判断是否展示


async def test_render_qr_terminal_decode_failure():
    login = LoginSession(
        login_id="lg_1", domain="item.jd.com", status=LoginState.QR_READY,
        qr_png=b"PNGBYTES",
    )
    service = FakeService(FakeLoginManager(qr_entry=login))

    from app.crawler.qr_render import QRDecodeError

    with _patched_qr_render(decode_error=QRDecodeError("识别不出内容")):
        resp = await render_qr_terminal_impl(service, login_id="lg_1")

    assert resp["status"] == "FAILED"
    assert resp["error_code"] == "QR_DECODE_FAILED"


async def test_render_qr_terminal_unknown_login_id():
    service = FakeService(FakeLoginManager(qr_entry=None))

    resp = await render_qr_terminal_impl(service, login_id="missing")

    assert resp["status"] == "FAILED"
    assert resp["error_code"] == "LOGIN_NOT_FOUND"


async def test_render_qr_terminal_when_disabled():
    resp = await render_qr_terminal_impl(FakeService(None), login_id="lg_1")
    assert resp["error_code"] == "LOGIN_INIT_FAILED"
