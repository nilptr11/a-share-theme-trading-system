"""Tushare 资讯抓取命令行入口。"""

import argparse
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from theme_trading.news.constants import DEFAULT_SOURCES
from theme_trading.news.fetcher import fetch_source, make_session
from theme_trading.news.writer import build_summary, write_archive_index, write_daily_docs


@dataclass(frozen=True)
class FetchConfig:
    cookie: str
    run_id: str
    docs_dir: Path
    sources: list[str]
    timeout: float
    delay: float


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
    parser.add_argument("--docs-dir", default="data/tushare-news", help="Markdown 归档根目录")
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
