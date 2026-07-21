from datetime import datetime, timezone

from app.crawler.login_persist import load_profile_cookies, persist_login_profile
from app.storage.profile_store import ProfileStore

_NOW = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)


class FakeDB:
    def __init__(self):
        self.profiles = {}

    async def upsert_profile(self, profile):
        self.profiles[profile.session_id] = profile


def _store(tmp_path):
    return ProfileStore(
        enc_dir=tmp_path / "data" / "profiles",
        work_root=tmp_path / "tmp" / "profiles",
        key="k",
    )


async def test_persist_creates_profile_and_seals_cookies(tmp_path):
    store = _store(tmp_path)
    db = FakeDB()

    profile = await persist_login_profile(
        cookies={"pt_key": "abc", "pt_pin": "user"},
        domain="www.jd.com",
        label="jd-主账号",
        store=store,
        db=db,
        session_id="jd-user-1",
        clock=lambda: _NOW,
        ttl_seconds=3600,
    )

    assert profile.session_id == "jd-user-1"
    assert profile.domain == "www.jd.com"
    assert profile.status == "ACTIVE"
    assert profile.expires_at == datetime(2026, 7, 21, 13, 0, tzinfo=timezone.utc)
    assert db.profiles["jd-user-1"].label == "jd-主账号"
    # 落盘的是密文，明文 cookie 不出现在 /data
    blob = store.enc_path("jd-user-1").read_bytes()
    assert b"pt_key" not in blob and b"abc" not in blob


async def test_persisted_cookies_roundtrip(tmp_path):
    store = _store(tmp_path)
    await persist_login_profile(
        cookies={"pt_key": "abc", "pt_pin": "user"},
        domain="www.jd.com", label=None, store=store, db=FakeDB(),
        session_id="s1", clock=lambda: _NOW, ttl_seconds=3600,
    )

    cookies = load_profile_cookies(store, "s1")
    assert cookies == {"pt_key": "abc", "pt_pin": "user"}


def test_load_cookies_missing_returns_empty(tmp_path):
    assert load_profile_cookies(_store(tmp_path), "never") == {}
