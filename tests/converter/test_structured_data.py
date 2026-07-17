from app.converter.structured_data import extract_json_ld, extract_open_graph

PRODUCT_PAGE = """
<html>
<head>
  <meta property="og:title" content="示例商品" />
  <meta property="og:image" content="https://cdn.example.com/main.jpg" />
  <meta property="og:description" content="商品描述" />
  <script type="application/ld+json">
  {
    "@type": "Product",
    "name": "示例商品",
    "sku": "SKU-123"
  }
  </script>
</head>
<body></body>
</html>
"""


def test_extract_json_ld_returns_single_object():
    result = extract_json_ld(PRODUCT_PAGE)
    assert result == [{"@type": "Product", "name": "示例商品", "sku": "SKU-123"}]


def test_extract_json_ld_flattens_array_payload():
    html = """
    <script type="application/ld+json">
    [{"@type": "Product", "name": "A"}, {"@type": "Offer", "price": "10"}]
    </script>
    """
    result = extract_json_ld(html)
    assert result == [
        {"@type": "Product", "name": "A"},
        {"@type": "Offer", "price": "10"},
    ]


def test_extract_json_ld_skips_malformed_blocks():
    html = """
    <script type="application/ld+json">{not valid json}</script>
    <script type="application/ld+json">{"@type": "Product", "name": "B"}</script>
    """
    result = extract_json_ld(html)
    assert result == [{"@type": "Product", "name": "B"}]


def test_extract_json_ld_returns_empty_list_when_absent():
    assert extract_json_ld("<html><body>no data here</body></html>") == []


def test_extract_open_graph_strips_prefix():
    og = extract_open_graph(PRODUCT_PAGE)
    assert og == {
        "title": "示例商品",
        "image": "https://cdn.example.com/main.jpg",
        "description": "商品描述",
    }


def test_extract_open_graph_returns_empty_dict_when_absent():
    assert extract_open_graph("<html><head></head><body></body></html>") == {}
