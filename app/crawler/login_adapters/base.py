"""站点登录适配器接口与选择（Phase 3b / M-P3-4）。

不同站点（京东、淘宝…）的二维码定位与扫码状态信号各异，抽象为适配器：
LoginManager 只依赖本接口，新增站点只加一个适配器、不动主流程。
"""
from typing import Protocol, runtime_checkable


@runtime_checkable
class LoginAdapter(Protocol):
    domain_patterns: tuple[str, ...]

    async def open_login(self, session: object, url: str) -> None:
        """在给定浏览器会话中打开登录页。"""
        ...

    async def capture_qr(self, session: object) -> bytes:
        """截取二维码元素，返回 PNG 字节。"""
        ...

    async def poll_status(self, session: object) -> str:
        """读取扫码状态：PENDING / SCANNED / SUCCESS / EXPIRED。"""
        ...


def match_domain(host: str, patterns: tuple[str, ...]) -> bool:
    host = (host or "").lower()
    return any(host == p or host.endswith(f".{p}") for p in patterns)


def select_adapter(adapters, host: str):
    for adapter in adapters:
        if match_domain(host, adapter.domain_patterns):
            return adapter
    return None
