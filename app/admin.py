"""域名规则（抓取白名单）运维 CLI。

与 MCP 服务（`python -m app.main`）相互独立：本命令只连数据库、执行一次
增删查后退出，不对外提供任何 MCP 服务。用于维护 `crawl_domain_rules`，让
白名单域名在 mode=auto 时直连指定抓取层（如 stealth），避免逐层升级带来的
多次请求触发目标站频率限制。

用法示例：
    python -m app.admin add-rule www.smzdm.com --mode stealth
    python -m app.admin list
    python -m app.admin get www.smzdm.com
    python -m app.admin remove www.smzdm.com
"""
import argparse
import asyncio
import sys
from typing import Any

from app.config import Settings
from app.storage.database import Database, DomainRule

_VALID_MODES = ("auto", "http", "browser", "stealth")


def _parse_status_codes(raw: str) -> list[int]:
    text = (raw or "").strip()
    if not text:
        return [403, 429, 503]
    try:
        return [int(part) for part in text.split(",") if part.strip()]
    except ValueError as exc:
        raise ValueError(
            f"--escalate-status-codes 必须是逗号分隔的整数，收到 {raw!r}"
        ) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="app.admin", description="维护抓取域名规则（白名单）"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add-rule", help="新增或更新域名规则（upsert）")
    add.add_argument("domain", help="域名，如 www.smzdm.com")
    add.add_argument(
        "--mode", dest="preferred_mode", default="stealth", choices=_VALID_MODES,
        help="mode=auto 时该域名的起始抓取层（默认 stealth，即直连 L3）",
    )
    add.add_argument("--min-content-bytes", type=int, default=2048)
    add.add_argument("--escalate-status-codes", default="403,429,503")
    add.add_argument("--source", default="manual")

    sub.add_parser("list", help="列出全部域名规则")

    get = sub.add_parser("get", help="查看单个域名规则")
    get.add_argument("domain")

    remove = sub.add_parser("remove", help="删除域名规则")
    remove.add_argument("domain")

    return parser


def _format_rule(rule: DomainRule) -> str:
    return (
        f"{rule.domain}\tmode={rule.preferred_mode}\t"
        f"min_content_bytes={rule.min_content_bytes}\t"
        f"escalate={rule.escalate_status_codes}\tsource={rule.source}"
    )


async def run_command(args: argparse.Namespace, db: Any) -> int:
    """执行子命令，返回进程退出码（0 成功，1 未找到，2 用法错误）。"""
    if args.command == "add-rule":
        rule = DomainRule(
            domain=args.domain,
            preferred_mode=args.preferred_mode,
            min_content_bytes=args.min_content_bytes,
            escalate_status_codes=_parse_status_codes(args.escalate_status_codes),
            source=args.source,
        )
        await db.upsert_domain_rule(rule)
        print(f"已保存域名规则：{args.domain} → mode={args.preferred_mode}")
        return 0

    if args.command == "list":
        rules = await db.list_domain_rules()
        if not rules:
            print("（暂无域名规则）")
            return 0
        for rule in rules:
            print(_format_rule(rule))
        return 0

    if args.command == "get":
        rule = await db.get_domain_rule(args.domain)
        if rule is None:
            print(f"未找到域名规则：{args.domain}")
            return 1
        print(_format_rule(rule))
        return 0

    if args.command == "remove":
        deleted = await db.delete_domain_rule(args.domain)
        if not deleted:
            print(f"未找到域名规则：{args.domain}")
            return 1
        print(f"已删除域名规则：{args.domain}")
        return 0

    return 2


async def _amain(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings()
    if not settings.database_url:
        print("DATABASE_URL 未配置，无法连接数据库。", file=sys.stderr)
        return 2
    db = await Database.connect(settings.database_url, min_size=1, max_size=2)
    try:
        return await run_command(args, db)
    finally:
        await db.close()


def main() -> None:
    raise SystemExit(asyncio.run(_amain()))


if __name__ == "__main__":
    main()
