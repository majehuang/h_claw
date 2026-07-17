from dataclasses import dataclass
from typing import Any

from bs4 import BeautifulSoup

from app.converter.cleaner import clean_html
from app.converter.images import extract_image_urls
from app.converter.markdown import build_markdown
from app.converter.structured_data import extract_json_ld, extract_open_graph


@dataclass(frozen=True)
class ConversionResult:
    markdown: str
    title: str | None
    json_ld: list[dict[str, Any]]
    images: list[str]


def convert_html_to_markdown(
    html: str,
    *,
    job_id: str,
    source_url: str,
    final_url: str,
    fetch_mode: str,
    status_code: int,
    fetched_at: str,
    content_language: str | None = None,
) -> ConversionResult:
    """按第 9 节处理顺序：先从原始 HTML 提取 JSON-LD/OG（清洗会去掉 <script>），
    再清洗生成 Markdown 正文，最后拼装 front matter 与附加区块。
    """
    json_ld = extract_json_ld(html)
    og = extract_open_graph(html)
    title = _resolve_title(html, json_ld, og)

    cleaned = clean_html(html, final_url)
    images = extract_image_urls(cleaned, json_ld, og, final_url)

    front_matter = {
        "job_id": job_id,
        "source_url": source_url,
        "final_url": final_url,
        "title": title,
        "fetched_at": fetched_at,
        "fetch_mode": fetch_mode,
        "status_code": status_code,
        "content_language": content_language,
    }

    markdown = build_markdown(cleaned, front_matter, images, json_ld)
    return ConversionResult(markdown=markdown, title=title, json_ld=json_ld, images=images)


def _resolve_title(
    html: str, json_ld: list[dict[str, Any]], og: dict[str, str]
) -> str | None:
    for item in json_ld:
        name = item.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    if og.get("title"):
        return og["title"]
    soup = BeautifulSoup(html, "lxml")
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    return None
