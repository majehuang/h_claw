import pytest

from app.storage.profile_store import ProfileDecryptError, ProfileStore


def _store(tmp_path, key="test-key-123"):
    enc = tmp_path / "data" / "profiles"     # 模拟 /data（持久，只放密文）
    work = tmp_path / "tmp" / "profiles"     # 模拟 tmpfs（明文工作区）
    return ProfileStore(enc_dir=enc, work_root=work, key=key)


def _write(dir_path, name, content):
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / name).write_text(content, encoding="utf-8")


def test_seal_then_load_roundtrip(tmp_path):
    store = _store(tmp_path)
    work = store.load("s1")            # 新 profile → 空目录
    _write(work, "cookies.txt", "session=abc")

    store.seal("s1", work)

    # 丢弃明文工作区后重新加载，内容应还原
    reloaded = store.load("s1")
    assert (reloaded / "cookies.txt").read_text(encoding="utf-8") == "session=abc"


def test_load_missing_returns_empty_dir(tmp_path):
    store = _store(tmp_path)
    work = store.load("never-sealed")
    assert work.exists()
    assert list(work.iterdir()) == []


def test_wrong_key_raises_decrypt_error(tmp_path):
    store = _store(tmp_path, key="right-key")
    work = store.load("s1")
    _write(work, "cookies.txt", "session=abc")
    store.seal("s1", work)

    other = _store(tmp_path, key="wrong-key")
    with pytest.raises(ProfileDecryptError) as exc:
        other.load("s1")
    assert exc.value.error_code == "PROFILE_DECRYPT_FAILED"


def test_corrupt_ciphertext_raises_decrypt_error(tmp_path):
    store = _store(tmp_path)
    work = store.load("s1")
    _write(work, "cookies.txt", "session=abc")
    store.seal("s1", work)

    enc = store.enc_path("s1")
    enc.write_bytes(enc.read_bytes()[:-3] + b"\x00\x00\x00")  # 破坏密文

    with pytest.raises(ProfileDecryptError):
        store.load("s1")


def test_data_dir_holds_only_ciphertext(tmp_path):
    store = _store(tmp_path)
    work = store.load("s1")
    _write(work, "cookies.txt", "session=secret-plaintext")
    store.seal("s1", work)

    enc_files = list((tmp_path / "data" / "profiles").iterdir())
    # /data 下只有 <id>.enc，没有明文、没有残留临时文件
    assert [p.name for p in enc_files] == ["s1.enc"]
    blob = (tmp_path / "data" / "profiles" / "s1.enc").read_bytes()
    assert b"secret-plaintext" not in blob


def test_seal_is_atomic_no_tmp_leftover(tmp_path):
    store = _store(tmp_path)
    work = store.load("s1")
    _write(work, "a.txt", "x")
    store.seal("s1", work)
    store.seal("s1", work)  # 覆盖写一次

    names = [p.name for p in (tmp_path / "data" / "profiles").iterdir()]
    assert names == ["s1.enc"]  # 无 .tmp 残留
