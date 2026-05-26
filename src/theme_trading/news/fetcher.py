"""Tushare 资讯页面抓取。"""

from typing import Any

import requests

from .constants import BASE_URL
from .parser import parse_news_page


def make_session(cookie: str) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Referer": "https://tushare.pro/news/sina",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
            "Cookie": cookie,
        }
    )
    return session

def fetch_source(session: requests.Session, slug: str, timeout: float) -> dict[str, Any]:
    url = f"{BASE_URL}/news/{slug}"
    response = session.get(url, timeout=timeout, allow_redirects=True)
    response.raise_for_status()
    return parse_news_page(response.text, slug)
