"""Tushare 资讯 Markdown 写入。"""

import time
from pathlib import Path
from typing import Any

from .constants import BASE_URL


def md_escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def build_summary(pages: list[dict[str, Any]], config: Any) -> dict[str, Any]:
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
        "- [稳定获取方式](../../docs/tushare-news/fetch-method.md)",
        "- [页面结构](../../docs/tushare-news/page-structure.md)",
        "",
        "## 抓取快照",
        "",
        "| 批次 | 来源统计 |",
        "| --- | --- |",
    ]
    lines.extend(f"| {run} | [{run}]({run}/sources.md) |" for run in runs)
    lines.append("")
    (docs_root / "README.md").write_text("\n".join(lines), encoding="utf-8")
