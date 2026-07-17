from app.converter.images import extract_image_urls

BASE_URL = "https://shop.example.com/product/123"


def test_prioritizes_json_ld_then_og_then_dom():
    json_ld = [{"@type": "Product", "image": "https://cdn.example.com/jsonld.jpg"}]
    og = {"image": "https://cdn.example.com/og.jpg"}
    html = '<img src="/images/dom.jpg" />'

    result = extract_image_urls(html, json_ld, og, BASE_URL)

    assert result == [
        "https://cdn.example.com/jsonld.jpg",
        "https://cdn.example.com/og.jpg",
        "https://shop.example.com/images/dom.jpg",
    ]


def test_flattens_json_ld_image_list_and_image_object():
    json_ld = [
        {
            "@type": "Product",
            "image": [
                "https://cdn.example.com/a.jpg",
                {"@type": "ImageObject", "url": "https://cdn.example.com/b.jpg"},
            ],
        }
    ]

    result = extract_image_urls("", json_ld, {}, BASE_URL)

    assert result == [
        "https://cdn.example.com/a.jpg",
        "https://cdn.example.com/b.jpg",
    ]


def test_dedupes_repeated_urls_keeping_first_occurrence_priority():
    json_ld = [{"@type": "Product", "image": "https://cdn.example.com/main.jpg"}]
    html = '<img src="https://cdn.example.com/main.jpg" /><img src="/images/detail.jpg" />'

    result = extract_image_urls(html, json_ld, {}, BASE_URL)

    assert result == [
        "https://cdn.example.com/main.jpg",
        "https://shop.example.com/images/detail.jpg",
    ]


def test_falls_back_to_data_src_when_src_missing():
    html = '<img data-src="/images/lazy.jpg" />'

    result = extract_image_urls(html, [], {}, BASE_URL)

    assert result == ["https://shop.example.com/images/lazy.jpg"]


def test_returns_empty_list_when_no_signals():
    assert extract_image_urls("<body></body>", [], {}, BASE_URL) == []
