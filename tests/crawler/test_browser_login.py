from datetime import datetime, timezone
from pathlib import Path

from app.crawler.browser_login import close_browser_login, open_browser_login

_NOW = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)


class FakeContext:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


class FakePage:
    def __init__(self, context):
        self.context = context


class FakeStore:
    def __init__(self):
        self.sealed = []

    def seal(self, session_id, work_dir):
        self.sealed.append((session_id, str(work_dir)))


class FakeDB:
    def __init__(self):
        self.profiles = {}

    async def upsert_profile(self, profile):
        self.profiles[profile.session_id] = profile


async def test_open_creates_context_and_tracks_user_data_dir(tmp_path):
    opened = {}

    async def launcher(udd):
        opened["udd"] = udd
        ctx = FakeContext()
        return ctx, FakePage(ctx)

    page = await open_browser_login(
        browser_launcher=launcher, tmp_root=tmp_path, id_factory=lambda: "ln1"
    )

    assert opened["udd"] == str(tmp_path / "ln1")
    assert Path(page._hermes_udd) == tmp_path / "ln1"


async def test_close_success_seals_profile_and_returns_session_id(tmp_path):
    ctx = FakeContext()
    page = FakePage(ctx)
    page._hermes_udd = tmp_path / "ln1"
    store, db = FakeStore(), FakeDB()

    session_id = await close_browser_login(
        page, success=True, domain="www.jd.com",
        store=store, db=db, session_id_factory=lambda: "jd-user",
        clock=lambda: _NOW, ttl_seconds=3600,
    )

    assert session_id == "jd-user"
    assert store.sealed == [("jd-user", str(tmp_path / "ln1"))]  # user_data_dir 加密封存
    assert db.profiles["jd-user"].domain == "www.jd.com"
    assert db.profiles["jd-user"].status == "ACTIVE"
    assert ctx.closed is True


async def test_close_failure_discards_and_closes(tmp_path):
    ctx = FakeContext()
    page = FakePage(ctx)
    page._hermes_udd = tmp_path / "ln1"
    store, db = FakeStore(), FakeDB()

    session_id = await close_browser_login(
        page, success=False, domain="www.jd.com",
        store=store, db=db, session_id_factory=lambda: "jd-user",
        clock=lambda: _NOW, ttl_seconds=3600,
    )

    assert session_id is None
    assert store.sealed == []       # 失败不落盘
    assert db.profiles == {}
    assert ctx.closed is True        # 无论成败都关闭上下文
