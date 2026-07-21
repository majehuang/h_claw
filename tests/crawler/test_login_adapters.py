from app.crawler.login_adapters.base import match_domain, select_adapter


class FakeAdapter:
    def __init__(self, patterns):
        self.domain_patterns = patterns


def test_match_domain_exact_and_subdomain():
    assert match_domain("www.jd.com", ("jd.com",)) is True
    assert match_domain("passport.jd.com", ("jd.com",)) is True
    assert match_domain("jd.com", ("jd.com",)) is True


def test_match_domain_rejects_unrelated():
    assert match_domain("evil-jd.com", ("jd.com",)) is False
    assert match_domain("taobao.com", ("jd.com",)) is False


def test_select_adapter_picks_matching():
    jd = FakeAdapter(("jd.com",))
    tb = FakeAdapter(("taobao.com", "tmall.com"))

    assert select_adapter([jd, tb], "item.jd.com") is jd
    assert select_adapter([jd, tb], "s.tmall.com") is tb


def test_select_adapter_returns_none_when_no_match():
    assert select_adapter([FakeAdapter(("jd.com",))], "www.baidu.com") is None
