import pytest

from app.crawler.profile_manager import ProfileManager
from app.storage.profile_store import ProfileStore

pytestmark = [pytest.mark.asyncio, pytest.mark.browser]


def _profile_manager(tmp_path):
    store = ProfileStore(
        enc_dir=tmp_path / "data" / "profiles",   # 持久卷：只放密文
        work_root=tmp_path / "tmp" / "profiles",  # tmpfs：明文工作区
        key="integration-key",
    )

    async def factory(work_dir):
        from scrapling.fetchers import AsyncStealthySession

        session = AsyncStealthySession(
            max_pages=1, headless=True, user_data_dir=str(work_dir)
        )
        await session.start()
        return session

    return ProfileManager(store=store, session_factory=factory, max_active_profiles=1)


async def test_cookie_persists_across_seal_and_reload(local_server, tmp_path):
    # 验证 §2/§4：持久 cookie 经「浏览器→加密落 /data→解密重载」后仍随请求发出，
    # 即登录态可跨会话复用；同时坐实 S3（tmpfs 加密回写闭环）。
    pm = _profile_manager(tmp_path)

    async with pm.use("acct-1") as session:
        await session.fetch(f"{local_server}/set-cookie")

    # 新会话：从密文重载 profile，cookie 应被带回
    async with pm.use("acct-1") as session:
        resp = await session.fetch(f"{local_server}/show-cookie")
        assert "profile_test=persisted123" in (resp.html_content or "")

    # /data 下只有密文
    enc_files = list((tmp_path / "data" / "profiles").iterdir())
    assert [p.name for p in enc_files] == ["acct-1.enc"]
