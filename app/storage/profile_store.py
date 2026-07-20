"""持久化浏览器 Profile 的加密存取（Phase 3a / M-P3-1）。

安全模型（见 phase-3 设计 §4.2 / §4.2.1）：
- 密文（AES-256-GCM）落在持久卷 `enc_dir`（对应 `/data/profiles`）。
- 明文只解到内存态 tmpfs 工作区 `work_root`（对应 `/tmp`），绝不明文落盘到 `/data`。
- 主密钥由部署环境注入，不在本模块持久化。
"""
import hashlib
import io
import os
import shutil
import tarfile
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_NONCE_BYTES = 12


class ProfileDecryptError(Exception):
    """密钥错误或密文损坏，无法解密 profile。"""

    def __init__(self, message: str):
        super().__init__(message)
        self.error_code = "PROFILE_DECRYPT_FAILED"


def _derive_key(passphrase: str) -> bytes:
    # AES-256 需要 32 字节密钥；由注入的主密钥经 SHA-256 派生（确定性、无需存盐）。
    return hashlib.sha256(passphrase.encode("utf-8")).digest()


def _tar_dir(src_dir: Path) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for entry in sorted(src_dir.rglob("*")):
            tar.add(entry, arcname=str(entry.relative_to(src_dir)))
    return buffer.getvalue()


def _untar_into(data: bytes, dest_dir: Path) -> None:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r") as tar:
        # filter="data" 阻止路径穿越/绝对路径等不安全条目（Python 3.12+）。
        tar.extractall(dest_dir, filter="data")


class ProfileStore:
    def __init__(self, *, enc_dir: Path, work_root: Path, key: str):
        self._enc_dir = Path(enc_dir)
        self._work_root = Path(work_root)
        self._key = _derive_key(key)

    def enc_path(self, session_id: str) -> Path:
        return self._enc_dir / f"{session_id}.enc"

    def exists(self, session_id: str) -> bool:
        return self.enc_path(session_id).exists()

    def load(self, session_id: str) -> Path:
        """把 profile 解密到 tmpfs 工作目录并返回其路径；无密文时返回空目录（新 profile）。"""
        work = self._work_root / session_id
        if work.exists():
            shutil.rmtree(work)
        work.mkdir(parents=True, exist_ok=True)

        enc = self.enc_path(session_id)
        if not enc.exists():
            return work

        plaintext = self._decrypt(enc.read_bytes())
        _untar_into(plaintext, work)
        return work

    def seal(self, session_id: str, work_dir: Path) -> None:
        """把 tmpfs 工作目录打包加密，原子写回持久卷。"""
        blob = self._encrypt(_tar_dir(Path(work_dir)))
        self._enc_dir.mkdir(parents=True, exist_ok=True)
        target = self.enc_path(session_id)
        tmp = target.with_name(f"{target.name}.tmp")
        tmp.write_bytes(blob)
        os.replace(tmp, target)

    def _encrypt(self, plaintext: bytes) -> bytes:
        nonce = os.urandom(_NONCE_BYTES)
        return nonce + AESGCM(self._key).encrypt(nonce, plaintext, None)

    def _decrypt(self, blob: bytes) -> bytes:
        if len(blob) <= _NONCE_BYTES:
            raise ProfileDecryptError("密文长度非法，可能已损坏。")
        nonce, ciphertext = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
        try:
            return AESGCM(self._key).decrypt(nonce, ciphertext, None)
        except InvalidTag as exc:
            raise ProfileDecryptError("密钥错误或密文损坏，无法解密 profile。") from exc
