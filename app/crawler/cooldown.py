"""挑战熔断冷却态的存储抽象（HC-002）。

orchestrator 只依赖 `CooldownStore` 接口：单测用进程内实现，生产用 DB 实现（跨重启
持久）。冷却态只保存 domain+session 维度的 next_allowed_at，绝不含 Cookie/令牌/页面。
"""
from datetime import datetime
from typing import Protocol


class CooldownStore(Protocol):
    async def remaining_seconds(self, key: str, now: datetime) -> int | None:
        """冷却剩余秒数；已过期或未设置返回 None。"""
        ...

    async def arm(self, key: str, until: datetime, reason: str | None = None) -> None:
        """设置/刷新该 key 的冷却截止时间。"""
        ...

    async def clear(self, key: str) -> None:
        """解除该 key 的冷却（成功恢复时调用，仅影响该 key）。"""
        ...


def _remaining(until: datetime | None, now: datetime) -> int | None:
    if until is None or now >= until:
        return None
    return max(1, int((until - now).total_seconds()))


class InMemoryCooldownStore:
    """进程内实现：与旧的字典行为一致，供单测与未配置 DB 时使用。"""

    def __init__(self) -> None:
        self._cooldowns: dict[str, datetime] = {}

    async def remaining_seconds(self, key: str, now: datetime) -> int | None:
        until = self._cooldowns.get(key)
        remaining = _remaining(until, now)
        if remaining is None:
            self._cooldowns.pop(key, None)
        return remaining

    async def arm(self, key: str, until: datetime, reason: str | None = None) -> None:
        self._cooldowns[key] = until

    async def clear(self, key: str) -> None:
        self._cooldowns.pop(key, None)


class DbCooldownStore:
    """DB 实现：冷却态落 challenge_cooldowns 表，跨进程/重启持久（HC-002）。"""

    def __init__(self, database) -> None:
        self._db = database

    async def remaining_seconds(self, key: str, now: datetime) -> int | None:
        until = await self._db.get_challenge_cooldown(key, now)
        return _remaining(until, now)

    async def arm(self, key: str, until: datetime, reason: str | None = None) -> None:
        await self._db.upsert_challenge_cooldown(key, until, reason)

    async def clear(self, key: str) -> None:
        await self._db.clear_challenge_cooldown(key)
