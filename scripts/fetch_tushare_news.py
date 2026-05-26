# /// script
# dependencies = ["requests>=2.32.0", "beautifulsoup4>=4.12.0", "lxml>=5.0.0", "python-dotenv>=1.0.0"]
# ///

from __future__ import annotations

import argparse
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

BASE_URL = "https://tushare.pro"
DEFAULT_SOURCES = [
    "xq",
    "yicai",
    "fenghuang",
    "10jqka",
    "jinrongjie",
    "sina",
    "yuncaijing",
    "cls",
    "eastmoney",
    "wallstreetcn",
]


@dataclass(frozen=True)
class FetchConfig:
    cookie: str
    run_id: str
    docs_dir: Path
    sources: list[str]
    timeout: float
    delay: float


def text_of(node: Any) -> str:
    return node.get_text(" ", strip=True) if node else ""


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


def fetch_source(session: requests.Session, slug: str, timeout: float) -> dict[str, Any]:
    url = f"{BASE_URL}/news/{slug}"
    response = session.get(url, timeout=timeout, allow_redirects=True)
    response.raise_for_status()
    return parse_news_page(response.text, slug)


def md_escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def build_summary(pages: list[dict[str, Any]], config: FetchConfig) -> dict[str, Any]:
    return {
        "base_url": f"{BASE_URL}/news",
        "run_id": config.run_id,
        "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "docs_dir": config.docs_dir.as_posix(),
        "sources": [
            {
                "slug": page["slug"],
                "name": page["current_source"],
                "url": page["url"],
                "channels": [{"name": channel["name"], "count": channel["count"]} for channel in page["channels"]],
                "total_items": page["total_items"],
            }
            for page in pages
        ],
    }


def write_daily_docs(docs_dir: Path, summary: dict[str, Any], pages: list[dict[str, Any]]) -> None:
    docs_dir.mkdir(parents=True, exist_ok=True)
    source_rows = []
    for source in summary["sources"]:
        channels = "、".join(f"{item['name']}({item['count']})" for item in source["channels"])
        source_rows.append(
            f"| {source['name']} | `{source['slug']}` | {source['total_items']} | {md_escape(channels)} | {source['url']} |"
        )

    (docs_dir / "sources.md").write_text(
        "\n".join(
            [
                "# 资讯源与频道清单",
                "",
                f"- 抓取批次：{summary['run_id']}",
                f"- 抓取时间：{summary['fetched_at']}",
                f"- 已解析资讯源：{len(summary['sources'])} 个",
                f"- 已解析新闻条目：{sum(source['total_items'] for source in summary['sources'])} 条",
                "",
                "| 来源 | slug | 条目数 | 频道 | URL |",
                "| --- | --- | ---: | --- | --- |",
                *source_rows,
                "",
            ]
        ),
        encoding="utf-8",
    )

    for page in pages:
        lines = [
            f"# {page['current_source']} 资讯快照",
            "",
            f"- 抓取批次：{summary['run_id']}",
            f"- 抓取时间：{summary['fetched_at']}",
            f"- slug：`{page['slug']}`",
            f"- URL：{page['url']}",
            f"- 条目数：{page['total_items']}",
            f"- 搜索控件：{'存在' if page['has_search'] else '未发现'}",
            "",
            "## 频道",
            "",
            "| 频道 | 条目数 |",
            "| --- | ---: |",
        ]
        lines.extend(f"| {md_escape(channel['name'])} | {channel['count']} |" for channel in page["channels"])
        for channel in page["channels"]:
            lines.extend(["", f"## {channel['name']}", ""])
            for item in channel["items"]:
                lines.append(f"- **{md_escape(item['time'])}** {md_escape(item['content'])}")
        lines.append("")
        (docs_dir / f"source-{page['slug']}.md").write_text("\n".join(lines), encoding="utf-8")


def write_archive_index(docs_root: Path) -> None:
    runs = sorted([path.name for path in docs_root.iterdir() if path.is_dir()], reverse=True)
    lines = [
        "# Tushare 资讯数据抓取归档",
        "",
        "抓取结果按分钟级批次目录保存，最新一次运行会更新这个索引。",
        "",
        "## 静态说明",
        "",
        "- [稳定获取方式](fetch-method.md)",
        "- [页面结构](page-structure.md)",
        "",
        "## 抓取快照",
        "",
        "| 批次 | 来源统计 |",
        "| --- | --- |",
    ]
    lines.extend(f"| {run} | [{run}]({run}/sources.md) |" for run in runs)
    lines.append("")
    (docs_root / "README.md").write_text("\n".join(lines), encoding="utf-8")


def normalize_sources(args: argparse.Namespace) -> list[str]:
    if args.all or not args.source:
        return DEFAULT_SOURCES
    unknown = sorted(set(args.source) - set(DEFAULT_SOURCES))
    if unknown:
        raise SystemExit(f"未知来源 slug：{', '.join(unknown)}；可选：{', '.join(DEFAULT_SOURCES)}")
    return args.source


def read_cookie(args: argparse.Namespace) -> str:
    load_dotenv(args.env_file)
    if args.cookie_file:
        cookie = Path(args.cookie_file).read_text(encoding="utf-8").strip()
    else:
        cookie = os.environ.get(args.cookie_env, "").strip()
    if not cookie:
        raise SystemExit(f"请先在 {args.env_file} 中设置 {args.cookie_env}，或使用 --cookie-file 指定 Cookie 文件")
    if not re.search(r"(^|;\s*)uid=", cookie) or not re.search(r"(^|;\s*)username=", cookie):
        raise SystemExit("Cookie 中未发现 uid/username，可能不是 Tushare 登录 Cookie")
    return cookie


def run(config: FetchConfig) -> dict[str, Any]:
    config.docs_dir.mkdir(parents=True, exist_ok=True)
    session = make_session(config.cookie)
    pages = []
    for index, slug in enumerate(config.sources, start=1):
        parsed = fetch_source(session, slug, config.timeout)
        pages.append(parsed)
        print(f"[{index}/{len(config.sources)}] {slug}: {parsed['current_source']} {parsed['total_items']} 条")
        if index < len(config.sources) and config.delay > 0:
            time.sleep(config.delay)
    summary = build_summary(pages, config)
    write_daily_docs(config.docs_dir, summary, pages)
    write_archive_index(config.docs_dir.parent)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="抓取 Tushare 资讯数据页面并生成清洗后的 Markdown")
    parser.add_argument("--all", action="store_true", help="抓取全部已知来源")
    parser.add_argument("--source", action="append", choices=DEFAULT_SOURCES, help="指定来源 slug，可重复传入")
    parser.add_argument("--docs-dir", default="docs/tushare-news", help="Markdown 归档根目录")
    parser.add_argument("--run-id", default=datetime.now().strftime("%Y-%m-%d-%H%M"), help="归档目录名，格式 YYYY-MM-DD-HHMM，默认当前分钟")
    parser.add_argument("--env-file", default=".env", help="读取环境变量的 .env 文件")
    parser.add_argument("--cookie-env", default="TUSHARE_COOKIE", help="读取 Cookie 的环境变量名")
    parser.add_argument("--cookie-file", help="从文件读取 Cookie，优先级高于环境变量")
    parser.add_argument("--timeout", type=float, default=30.0, help="单请求超时时间，秒")
    parser.add_argument("--delay", type=float, default=0.3, help="来源之间的间隔，秒")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}-\d{4}", args.run_id):
        raise SystemExit("--run-id 必须是 YYYY-MM-DD-HHMM 格式")
    config = FetchConfig(
        cookie=read_cookie(args),
        run_id=args.run_id,
        docs_dir=Path(args.docs_dir) / args.run_id,
        sources=normalize_sources(args),
        timeout=args.timeout,
        delay=args.delay,
    )
    summary = run(config)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
