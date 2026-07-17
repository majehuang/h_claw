import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from bs4 import BeautifulSoup, Comment

from app.converter.structured_data import extract_json_ld, extract_open_graph

_SIGNATURES_PATH = Path(__file__).parent / "challenge_signatures.yaml"
_SIGNATURES = yaml.safe_load(_SIGNATURES_PATH.read_text(encoding="utf-8"))

_KEYWORDS = [k.lower() for k in _SIGNATURES.get("keywords", [])]
_SELECTORS = _SIGNATURES.get("selectors", [])
_LOGIN_PATH_PATTERNS = _SIGNATURES.get("login_path_patterns", [])
_CAPTCHA_DOMAINS = _SIGNATURES.get("captcha_domains", [])

_PRICE_PATTERN = re.compile(r"[¥$€£]\s?\d|NT\$\s?\d|\d+\s?元")
_SPA_ROOT_IDS = ("app", "root", "__next")


@dataclass(frozen=True)
class FetchResponse:
    request_url: str
    final_url: str
    status_code: int
    html: str


@dataclass(frozen=True)
class DomainRuleDefaults:
    min_content_bytes: int = 2048
    escalate_status_codes: tuple[int, ...] = (403, 429, 503)


@dataclass(frozen=True)
class DetectionResult:
    ok: bool
    reason: str
    detail: str = ""


def _visible_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    for comment in soup.find_all(string=lambda node: isinstance(node, Comment)):
        comment.extract()
    return soup.get_text(strip=True)


def _host_matches_captcha_domain(host: str) -> bool:
    return any(host == domain or host.endswith(f".{domain}") for domain in _CAPTCHA_DOMAINS)


def _is_same_site(request_host: str, final_host: str) -> bool:
    if request_host == final_host:
        return True
    return final_host.endswith(f".{request_host}") or request_host.endswith(f".{final_host}")


def _check_status(
    response: FetchResponse, rule: DomainRuleDefaults
) -> DetectionResult | None:
    if response.status_code in rule.escalate_status_codes:
        return DetectionResult(False, "blocked_status", f"status={response.status_code}")
    return None


def _check_redirect_target(
    response: FetchResponse, rule: DomainRuleDefaults
) -> DetectionResult | None:
    parsed = urlsplit(response.final_url)
    host = parsed.hostname or ""
    if _host_matches_captcha_domain(host):
        return DetectionResult(False, "captcha_redirect", f"host={host}")
    if any(parsed.path.startswith(p) for p in _LOGIN_PATH_PATTERNS):
        return DetectionResult(False, "login_redirect", f"path={parsed.path}")
    return None


def _check_challenge_markers(
    response: FetchResponse, rule: DomainRuleDefaults
) -> DetectionResult | None:
    lowered = response.html.lower()
    for keyword in _KEYWORDS:
        if keyword in lowered:
            return DetectionResult(False, "captcha_detected", f"keyword={keyword}")
    soup = BeautifulSoup(response.html, "lxml")
    for selector in _SELECTORS:
        if soup.select_one(selector):
            return DetectionResult(False, "captcha_detected", f"selector={selector}")
    return None


def _check_spa_shell(
    response: FetchResponse, rule: DomainRuleDefaults
) -> DetectionResult | None:
    if _visible_text(response.html):
        return None
    soup = BeautifulSoup(response.html, "lxml")
    for root_id in _SPA_ROOT_IDS:
        if not soup.find(id=root_id):
            continue
        json_ld = extract_json_ld(response.html)
        og = extract_open_graph(response.html)
        if not json_ld and not og:
            return DetectionResult(False, "spa_shell", f"root_id={root_id}")
    return None


def _check_content_length(
    response: FetchResponse, rule: DomainRuleDefaults
) -> DetectionResult | None:
    byte_length = len(_visible_text(response.html).encode("utf-8"))
    if byte_length < rule.min_content_bytes:
        return DetectionResult(False, "short_content", f"bytes={byte_length}")
    return None


def _check_structured_signals(
    response: FetchResponse, rule: DomainRuleDefaults
) -> DetectionResult | None:
    soup = BeautifulSoup(response.html, "lxml")
    has_title = bool(soup.title and soup.title.string and soup.title.string.strip())
    json_ld = extract_json_ld(response.html)
    og = extract_open_graph(response.html)
    has_price = bool(_PRICE_PATTERN.search(response.html))
    if has_title or json_ld or og.get("title") or og.get("description") or has_price:
        return None
    return DetectionResult(False, "no_structured_signal", "no title/json-ld/og/price")


def _check_url_mismatch(
    response: FetchResponse, rule: DomainRuleDefaults
) -> DetectionResult | None:
    request_host = urlsplit(response.request_url).hostname or ""
    final_host = urlsplit(response.final_url).hostname or ""
    if request_host and final_host and not _is_same_site(request_host, final_host):
        return DetectionResult(False, "url_mismatch", f"{request_host} -> {final_host}")
    return None


_CHECKS: tuple[Callable[[FetchResponse, DomainRuleDefaults], DetectionResult | None], ...] = (
    _check_status,
    _check_redirect_target,
    _check_challenge_markers,
    _check_spa_shell,
    _check_content_length,
    _check_structured_signals,
    _check_url_mismatch,
)


def detect(
    response: FetchResponse, rule: DomainRuleDefaults = DomainRuleDefaults()
) -> DetectionResult:
    """按第 7.6 节检测链依次判定，命中即返回。

    只负责识别信号并分类原因，是否升级到下一层由 orchestrator（M6）
    结合当前所处层级决定。
    """
    for check in _CHECKS:
        result = check(response, rule)
        if result is not None:
            return result
    return DetectionResult(True, "ok")
