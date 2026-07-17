import ipaddress
import socket
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit

ALLOWED_SCHEMES = {"http", "https"}

_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

Resolver = Callable[[str], Iterable[str]]


class URLValidationError(Exception):
    def __init__(self, error_code: str, message: str):
        self.error_code = error_code
        super().__init__(message)


@dataclass(frozen=True)
class ValidatedURL:
    url: str
    hostname: str
    resolved_ips: tuple[str, ...]


def default_resolver(hostname: str) -> list[str]:
    infos = socket.getaddrinfo(hostname, None)
    return sorted({info[4][0] for info in infos})


def _parse_hostname(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in ALLOWED_SCHEMES:
        raise URLValidationError("INVALID_URL", f"不支持的协议: {parts.scheme!r}")
    if parts.username or parts.password:
        raise URLValidationError("INVALID_URL", "URL 不允许包含用户名或密码")
    if not parts.hostname:
        raise URLValidationError("INVALID_URL", "URL 缺少主机名")
    return parts.hostname


def _check_ip_allowed(ip_str: str) -> None:
    ip = ipaddress.ip_address(ip_str)
    for network in _BLOCKED_NETWORKS:
        if ip in network:
            raise URLValidationError("SSRF_BLOCKED", f"禁止访问私有/保留地址: {ip}")


def validate_public_http_url(
    url: str, resolver: Resolver = default_resolver
) -> ValidatedURL:
    """校验 URL 协议合法且解析出的全部 IP 均为公网地址。

    每次重定向后应对新的 URL 重新调用本函数（第 14.1 节），调用方应基于
    resolved_ips 中已校验过的具体 IP 建立连接，而不是在连接阶段重新解析
    域名，以避免 DNS rebinding。
    """
    hostname = _parse_hostname(url)
    resolved_ips = tuple(resolver(hostname))
    if not resolved_ips:
        raise URLValidationError("INVALID_URL", f"无法解析域名: {hostname}")
    for ip_str in resolved_ips:
        _check_ip_allowed(ip_str)
    return ValidatedURL(url=url, hostname=hostname, resolved_ips=resolved_ips)
