import yaml

from app.converter.markdown import build_markdown

FRONT_MATTER = {
    "job_id": "cr_019f",
    "source_url": "https://shop.example.com/product/123",
    "final_url": "https://shop.example.com/product/123",
    "title": "商品名称",
    "fetched_at": "2026-07-17T12:00:00+08:00",
    "fetch_mode": "browser",
    "status_code": 200,
    "content_language": "zh-CN",
}


def _split_front_matter(markdown: str) -> tuple[dict, str]:
    assert markdown.startswith("---\n")
    _, fm_block, body = markdown.split("---\n", 2)
    return yaml.safe_load(fm_block), body


def test_front_matter_roundtrips_and_forces_untrusted_flag():
    markdown = build_markdown("<p>正文</p>", FRONT_MATTER, images=[], json_ld=[])

    fm, _ = _split_front_matter(markdown)

    assert fm["job_id"] == "cr_019f"
    assert fm["title"] == "商品名称"
    assert fm["untrusted_external_content"] is True


def test_untrusted_flag_cannot_be_overridden_by_caller():
    malicious_front_matter = {**FRONT_MATTER, "untrusted_external_content": False}
    markdown = build_markdown("<p>正文</p>", malicious_front_matter, images=[], json_ld=[])

    fm, _ = _split_front_matter(markdown)
    assert fm["untrusted_external_content"] is True


def test_converts_body_html_to_markdown():
    markdown = build_markdown(
        "<h1>商品名称</h1><p>价格：NT$ 1,990</p>", FRONT_MATTER, images=[], json_ld=[]
    )
    _, body = _split_front_matter(markdown)

    assert "# 商品名称" in body
    assert "价格：NT$ 1,990" in body


def test_appends_image_section_when_images_present():
    markdown = build_markdown(
        "<p>正文</p>",
        FRONT_MATTER,
        images=["https://cdn.example.com/main.jpg", "https://cdn.example.com/detail-1.jpg"],
        json_ld=[],
    )
    _, body = _split_front_matter(markdown)

    assert "## 商品图片" in body
    assert "![商品图片 1](https://cdn.example.com/main.jpg)" in body
    assert "![商品图片 2](https://cdn.example.com/detail-1.jpg)" in body


def test_omits_image_section_when_no_images():
    markdown = build_markdown("<p>正文</p>", FRONT_MATTER, images=[], json_ld=[])
    _, body = _split_front_matter(markdown)
    assert "## 商品图片" not in body


def test_appends_structured_data_section_as_json_block():
    markdown = build_markdown(
        "<p>正文</p>",
        FRONT_MATTER,
        images=[],
        json_ld=[{"@type": "Product", "name": "商品名称", "sku": "SKU-123"}],
    )
    _, body = _split_front_matter(markdown)

    assert "## 结构化数据" in body
    assert '"sku": "SKU-123"' in body


def test_omits_structured_data_section_when_absent():
    markdown = build_markdown("<p>正文</p>", FRONT_MATTER, images=[], json_ld=[])
    _, body = _split_front_matter(markdown)
    assert "## 结构化数据" not in body
