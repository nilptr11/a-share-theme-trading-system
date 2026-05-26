# 稳定获取方式

## 结论

`https://tushare.pro/news` 直接访问时可能只返回前端壳页；具体来源页如 `/news/eastmoney` 在携带有效登录 Cookie 时会返回完整服务端渲染 HTML。稳定方案是固定请求来源页、在内存中解析 HTML、只落盘清洗后的 Markdown。

## 运行命令

复制 `.env.example` 为 `.env`，填入登录 Cookie：

```bash
cp .env.example .env
```

```dotenv
TUSHARE_COOKIE=uid=...; username=...
```

然后运行：

```bash
uv run fetch-tushare-news --all
```

默认输出到当前分钟的批次目录，例如：

```text
data/tushare-news/YYYY-MM-DD-HHMM/
```

补抓或重跑指定批次：

```bash
uv run fetch-tushare-news --all --run-id 2026-05-25-1955
```

只抓取指定来源：

```bash
uv run fetch-tushare-news --source eastmoney --source sina
```

## 输出

- `data/tushare-news/YYYY-MM-DD-HHMM/sources.md`：该批次来源与频道统计。
- `data/tushare-news/YYYY-MM-DD-HHMM/source-*.md`：该批次各来源完整快照。
- `data/tushare-news/README.md`：批次归档索引。
- `docs/tushare-news/page-structure.md`：页面结构说明。
- `docs/tushare-news/fetch-method.md`：稳定抓取方式说明。

## 稳定性检查

脚本会检查以下异常并失败退出：

- 返回 `/weborder/#/login` 或 Vue 前端壳页，说明 Cookie 失效或未登录。
- 未解析到 `#data_source_head` 来源导航。
- 未解析到 `#channel_head` 频道。

## 请求头要点

- 配置层面只需要 `TUSHARE_COOKIE`。
- 默认从 `.env` 读取，也可以用 `--env-file` 指定其它 env 文件。
- 脚本内部仍保留浏览器 `User-Agent`、`Accept-Language`、`Referer` 作为稳定性兜底。
- 不建议把 Cookie 写入脚本或 Markdown。
- 原始 HTML 和中间 JSON 不落盘。
