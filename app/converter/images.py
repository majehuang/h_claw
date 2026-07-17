from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup


def _flatten_json_ld_images(json_ld: list[dict[str, Any]]) -> list[str]:
    urls: list[str] = []
    for item in json_ld:
        image = item.get("image")
        if image is None:
            continue
        if isinstance(image, str):
            urls.append(image)
        elif isinstance(image, list):
            for entry in image:
                if isinstance(entry, str):
                    urls.append(entry)
                elif isinstance(entry, dict) and "url" in entry:
                    urls.append(entry["url"])
        elif isinstance(image, dict) and "url" in image:
            urls.append(image["url"])
    return urls


def extract_image_urls(
    html: str, json_ld: list[dict[str, Any]], og: dict[str, str], base_url: str
) -> list[str]:
    """按优先级提取商品图片：JSON-LD → Open Graph → DOM。

    XHR 捕获的图片列表和渲染后懒加载出现的图片（第 10 节优先级 3、5）
    依赖浏览器层，留给 M5 在浏览器抓取路径中补充。
    """
    ordered: list[str] = []
    seen: set[str] = set()

    def _add(url: str | None) -> None:
        if not url:
            return
        absolute = urljoin(base_url, url)
        if absolute not in seen:
            seen.add(absolute)
            ordered.append(absolute)

    for url in _flatten_json_ld_images(json_ld):
        _add(url)

    _add(og.get("image"))

    soup = BeautifulSoup(html, "lxml")
    for img in soup.find_all("img"):
        _add(img.get("src") or img.get("data-src"))

    return ordered
