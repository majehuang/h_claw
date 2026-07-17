import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Comment, Tag

_ZERO_WIDTH_CHARS = re.compile("[​‌‍﻿]")

_REMOVE_TAGS = {"script", "style", "noscript", "template", "nav", "footer"}

_URL_ATTRS = ("href", "src", "data-src")


def _is_hidden(tag: Tag) -> bool:
    if tag.has_attr("hidden"):
        return True
    style = (tag.get("style") or "").replace(" ", "").lower()
    return "display:none" in style or "visibility:hidden" in style


def _absolutize_srcset(value: str, base_url: str) -> str:
    parts = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        bits = item.split(" ", 1)
        absolute_url = urljoin(base_url, bits[0])
        parts.append(absolute_url if len(bits) == 1 else f"{absolute_url} {bits[1]}")
    return ", ".join(parts)


def _absolutize_urls(soup: BeautifulSoup, base_url: str) -> None:
    for tag in soup.find_all(True):
        for attr in _URL_ATTRS:
            if tag.has_attr(attr):
                tag[attr] = urljoin(base_url, tag[attr])
        if tag.has_attr("srcset"):
            tag["srcset"] = _absolutize_srcset(tag["srcset"], base_url)


def clean_html(html: str, base_url: str) -> str:
    soup = BeautifulSoup(html, "lxml")

    for comment in soup.find_all(string=lambda node: isinstance(node, Comment)):
        comment.extract()

    for tag_name in _REMOVE_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    for tag in soup.find_all(True):
        if tag.parent is None:
            continue
        if _is_hidden(tag):
            tag.decompose()

    _absolutize_urls(soup, base_url)

    return _ZERO_WIDTH_CHARS.sub("", str(soup))
