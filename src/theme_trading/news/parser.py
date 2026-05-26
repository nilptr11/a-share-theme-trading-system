"""Tushare 资讯页面解析。"""

from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .constants import BASE_URL


def text_of(node: Any) -> str:
    return node.get_text(" ", strip=True) if node else ""



def parse_news_page(html: str, slug: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")
    meta = {}
    for item in soup.select("meta"):
        name = item.get("name") or item.get("property") or item.get("http-equiv")
        content = item.get("content")
        if name and content:
            meta[name] = content

    navigation = [
        {"text": text_of(link), "href": urljoin(BASE_URL, link.get("href", ""))}
        for link in soup.select("#navigation a")
        if text_of(link)
    ]

    data_sources = []
    for span in soup.select("#data_source_head span.source_name"):
        link = span.find("a")
        if not link:
            continue
        href = link.get("href", "")
        data_sources.append(
            {
                "name": text_of(link),
                "slug": href.rstrip("/").split("/")[-1],
                "href": urljoin(BASE_URL, href),
                "current": "cur" in (span.get("class") or []),
            }
        )

    channels = []
    for channel in soup.select("#channel_head .channel_name"):
        name = text_of(channel)
        container = soup.find(id=f"news_{name}")
        items = []
        if container:
            for item in container.select(".news_item"):
                items.append(
                    {
                        "time": text_of(item.select_one(".news_datetime")),
                        "content": text_of(item.select_one(".news_content")),
                    }
                )
        channels.append({"name": name, "count": len(items), "items": items})

    current_source = next((source["name"] for source in data_sources if source["current"]), "")
    result = {
        "slug": slug,
        "url": f"{BASE_URL}/news/{slug}",
        "title": text_of(soup.title),
        "meta": meta,
        "navigation": navigation,
        "data_sources": data_sources,
        "current_source": current_source,
        "channels": channels,
        "total_items": sum(channel["count"] for channel in channels),
        "has_search": soup.select_one("#search-input") is not None and soup.select_one("#search-button") is not None,
    }
    validate_page(result, html)
    return result


def validate_page(parsed: dict[str, Any], html: str) -> None:
    if "/weborder/#/login" in html or "We're sorry but Tushare数据 doesn't work properly" in html:
        raise RuntimeError("返回的是登录页或前端壳页，请更新 TUSHARE_COOKIE 后重试")
    if not parsed["data_sources"] or not parsed["current_source"]:
        raise RuntimeError("未解析到资讯来源导航，可能是 Cookie 失效或页面结构变化")
    if not parsed["channels"]:
        raise RuntimeError("未解析到频道列表，可能是页面结构变化")

