import json
from typing import Any

from bs4 import BeautifulSoup


def extract_json_ld(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    results: list[dict[str, Any]] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, list):
            results.extend(item for item in payload if isinstance(item, dict))
        elif isinstance(payload, dict):
            results.append(payload)
    return results


def extract_open_graph(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "lxml")
    og: dict[str, str] = {}
    for meta in soup.find_all("meta", attrs={"property": True, "content": True}):
        property_name = meta["property"]
        if not property_name.startswith("og:"):
            continue
        og[property_name.removeprefix("og:")] = meta["content"]
    return og
