import json
from typing import Any

import yaml
from markdownify import markdownify as html_to_markdown


def build_markdown(
    cleaned_html: str,
    front_matter: dict[str, Any],
    images: list[str],
    json_ld: list[dict[str, Any]],
) -> str:
    body = html_to_markdown(cleaned_html, heading_style="ATX").strip()
    sections = [body]

    if images:
        image_block = "\n\n".join(
            f"![商品图片 {i}]({url})" for i, url in enumerate(images, start=1)
        )
        sections.append(f"## 商品图片\n\n{image_block}")

    if json_ld:
        payload = json_ld[0] if len(json_ld) == 1 else json_ld
        json_block = json.dumps(payload, ensure_ascii=False, indent=2)
        sections.append(f"## 结构化数据\n\n```json\n{json_block}\n```")

    # untrusted_external_content 是安全边界标记（第 14.3 节），始终为 true，
    # 不接受调用方覆盖，避免遗漏或被误改导致 Agent 误信页面内容。
    full_front_matter = {**front_matter, "untrusted_external_content": True}
    front_matter_yaml = yaml.safe_dump(
        full_front_matter, allow_unicode=True, sort_keys=False
    ).strip()

    document_body = "\n\n".join(sections)
    return f"---\n{front_matter_yaml}\n---\n\n{document_body}\n"
