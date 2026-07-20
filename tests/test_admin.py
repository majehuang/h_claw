import pytest

from app.admin import build_parser, run_command
from app.storage.database import DomainRule


class FakeDB:
    def __init__(self, rules=None):
        self._rules = {r.domain: r for r in (rules or [])}
        self.upserts = []
        self.deleted = []

    async def upsert_domain_rule(self, rule):
        self.upserts.append(rule)
        self._rules[rule.domain] = rule

    async def get_domain_rule(self, domain):
        return self._rules.get(domain)

    async def list_domain_rules(self):
        return [self._rules[d] for d in sorted(self._rules)]

    async def delete_domain_rule(self, domain):
        self.deleted.append(domain)
        return self._rules.pop(domain, None) is not None


def _parse(argv):
    return build_parser().parse_args(argv)


@pytest.mark.asyncio
async def test_add_rule_upserts_parsed_values():
    db = FakeDB()
    args = _parse([
        "add-rule", "www.smzdm.com", "--mode", "stealth",
        "--min-content-bytes", "4096", "--escalate-status-codes", "403,429",
    ])

    code = await run_command(args, db)

    assert code == 0
    assert len(db.upserts) == 1
    rule = db.upserts[0]
    assert rule.domain == "www.smzdm.com"
    assert rule.preferred_mode == "stealth"
    assert rule.min_content_bytes == 4096
    assert rule.escalate_status_codes == [403, 429]


@pytest.mark.asyncio
async def test_add_rule_defaults_to_stealth():
    db = FakeDB()
    args = _parse(["add-rule", "www.smzdm.com"])

    await run_command(args, db)

    assert db.upserts[0].preferred_mode == "stealth"
    assert db.upserts[0].escalate_status_codes == [403, 429, 503]


def test_add_rule_rejects_invalid_mode():
    # argparse choices 拦截非法 mode，退出码 2。
    with pytest.raises(SystemExit) as exc:
        _parse(["add-rule", "x.com", "--mode", "turbo"])
    assert exc.value.code == 2


@pytest.mark.asyncio
async def test_add_rule_rejects_non_integer_status_codes():
    db = FakeDB()
    args = _parse(["add-rule", "x.com", "--escalate-status-codes", "403,abc"])
    with pytest.raises(ValueError):
        await run_command(args, db)


@pytest.mark.asyncio
async def test_list_outputs_rules(capsys):
    db = FakeDB(rules=[
        DomainRule(domain="a.com", preferred_mode="stealth"),
        DomainRule(domain="b.com", preferred_mode="browser"),
    ])
    args = _parse(["list"])

    code = await run_command(args, db)

    out = capsys.readouterr().out
    assert code == 0
    assert "a.com" in out and "stealth" in out
    assert "b.com" in out and "browser" in out


@pytest.mark.asyncio
async def test_list_empty(capsys):
    args = _parse(["list"])
    code = await run_command(args, FakeDB())
    assert code == 0
    assert capsys.readouterr().out.strip() != ""


@pytest.mark.asyncio
async def test_get_missing_returns_1(capsys):
    args = _parse(["get", "missing.com"])
    code = await run_command(args, FakeDB())
    assert code == 1


@pytest.mark.asyncio
async def test_remove_deletes_and_returns_0():
    db = FakeDB(rules=[DomainRule(domain="a.com", preferred_mode="stealth")])
    args = _parse(["remove", "a.com"])

    code = await run_command(args, db)

    assert code == 0
    assert db.deleted == ["a.com"]
    assert await db.get_domain_rule("a.com") is None


@pytest.mark.asyncio
async def test_remove_missing_returns_1():
    db = FakeDB()
    args = _parse(["remove", "missing.com"])
    code = await run_command(args, db)
    assert code == 1
