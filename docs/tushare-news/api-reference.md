# Tushare API 接口参考

## 接口清单（已接入，共 13 个）

### 市场级

| 函数 | Tushare API | doc_id | 积分 | 用途 |
|------|------------|--------|------|------|
| `fetch_index_daily` | `index_daily` | 95 | 2000 | 指数日线（上证/深证/创业板 OHLCV） |
| `fetch_limit_list` | `limit_list` | 298 | 5000 | 涨跌停和炸板明细（U/D/Z） |
| `fetch_stk_limit` | `stk_limit` | 356 | 8000 | 每日涨跌停价格 + 连板统计 |
| `fetch_limit_cpt_list` | `limit_cpt_list` | 357 | 8000 | 涨停最强板块统计（板块排名+持续天数） |
| `fetch_moneyflow_hsgt` | `moneyflow_hsgt` | 47 | 2000 | 沪深港通资金流向（北向/南向） |

### 板块级

| 函数 | Tushare API | doc_id | 积分 | 用途 |
|------|------------|--------|------|------|
| `fetch_ths_index` | `ths_index` | 259 | 6000 | 同花顺板块分类列表（名称→代码） |
| `fetch_ths_daily` | `ths_daily` | 260 | 6000 | 板块指数日线（涨跌幅/成交额/换手率） |
| `fetch_ths_member` | `ths_member` | 261 | 6000 | 板块成分股（代码+名称） |

### 个股级

| 函数 | Tushare API | doc_id | 积分 | 用途 |
|------|------------|--------|------|------|
| `fetch_daily` | `daily` | 27 | 注册即可 | A股日线（OHLCV，单日最多 6000 条） |
| `fetch_daily_basic` | `daily_basic` | 32 | 2000 | 每日指标（换手率/流通市值/PE/PB） |
| `fetch_stock_basic` | `stock_basic` | 25 | 2000 | 股票列表（代码/名称/行业/上市日期） |
| `fetch_moneyflow` | `moneyflow` | 170 | 2000 | 个股资金流向（小单/中单/大单/超大单） |

### 辅助

| 函数 | Tushare API | doc_id | 积分 | 用途 |
|------|------------|--------|------|------|
| `fetch_trade_cal` | `trade_cal` | 26 | 注册即可 | 交易日历（判断是否交易日） |

---

## 交易系统字段映射

### 市场评分四维度 → API 字段

| 评分维度 | 来源接口 | 关键字段 | 计算逻辑 |
|----------|---------|---------|---------|
| 指数 (0-2) | `index_daily` | `close` | `close > MA20` 且 `MA20↑` = 2 分 |
| 成交量 (0-2) | `index_daily` | `amount`（上证+深证） | 今日成交额 / 5日均值 ≥ 1.2 = 2 分 |
| 情绪 (0-3) | `limit_list` | `limit`(U/D/Z), `limit_times` | 涨停数/跌停数/炸板率/连板高度综合 |
| 主线 (0-3) | `limit_cpt_list` | `days`, `name` | 最强板块持续 ≥ 4 天 = 3 分 |

### 硬规则检查 → API 字段

| 硬规则 | 接口 | 字段 | 触发条件 |
|--------|------|------|---------|
| 连续 3 日缩量空仓 | `index_daily` | `amount` | 连续 3 日 < 5 日均值 0.85 倍 |
| 炸板率 ≥ 40% | `limit_list` | `limit` | Z 类占比 ≥ 40% |
| 指数单日跌幅 ≥ 3% | `index_daily` | `pct_chg` | `pct_chg` ≤ -3 |

### 主线识别五条件 → API 字段

| 主线条件 | 接口 | 字段 |
|----------|------|------|
| 板块连续 2 日强于市场 | `ths_daily` + `index_daily` | `pct_change` vs `pct_chg` |
| 板块成交额 ≥ 5 日均量 1.3 倍 | `ths_daily` | `vol` |
| 板块内涨停 ≥ 5 只 | `limit_list` + `ths_member` | `limit`="U" + `con_code` |
| 核心股成交额进全市场前 50 | `daily` | `amount` |
| 分歧后资金回流 | `moneyflow` | `net_mf_amount` |

### 个股强势股条件 → API 字段

| 条件 | 接口 | 字段 |
|------|------|------|
| 成交额板块前 5 / 全市场前 50 | `daily` | `amount` |
| 近 5 日涨幅排板块前 20% | `daily` | `pct_chg` |
| 股价在均线之上 | `daily` | `close` vs MA5/MA10/MA20 |
| 突破近 20 日新高 | `daily` | `high` |
| 流动性底线 | `daily_basic` | `turnover_rate`(≥2%), `circ_mv`(≥20亿) |

### 买点条件 → API 字段

| 买点 | 核心指标 | 来源字段 |
|------|---------|---------|
| 买点一（放量突破） | 横盘 5 日、突破 20 日高点、量 ≥ 1.5 倍 | `close`, `high`, `vol` |
| 买点二（主升回踩） | 站上 MA5 ≥ 3 日、缩量 ≤ 70%/80%、不破 MA5 | `close`, `vol`, MA5 |
| 买点三（突破确认） | 前有 60 日新高、回踩不破突破位、缩量 ≤ 60% | `close`, `high`, `vol` |
| 买点四（趋势均线） | 沿 MA10/20 ≥ 10 日、涨幅 ≤ 50%、首次回踩 | `close`, MA10/MA20 |

---

## 调用关系速查

```
daily-scan
  ├─ compute_market_score()
  │   ├─ fetch_index_daily('000001.SH')     → 指数维度
  │   ├─ fetch_index_daily('399001.SZ')     → 成交量维度
  │   ├─ fetch_limit_list(trade_date)       → 情绪维度
  │   └─ fetch_limit_cpt_list(trade_date)   → 主线维度
  │
  ├─ find_main_themes()
  │   ├─ fetch_ths_daily(trade_date)        → 当日全板块
  │   ├─ fetch_ths_index()                  → 板块名称映射
  │   ├─ fetch_index_daily('000001.SH')     → 大盘基准
  │   ├─ fetch_ths_daily(ts_code=...)       → 候选板块历史 (×N)
  │   ├─ fetch_ths_member(ts_code)          → 板块成分股 (×N)
  │   └─ fetch_limit_list(limit_type='U')   → 板块内涨停统计
  │
  ├─ filter_core_stocks()
  │   ├─ fetch_daily(trade_date)            → 全市场日线
  │   └─ fetch_daily_basic(trade_date)      → 换手率/流通市值
  │
  └─ scan_buy_points()
      └─ fetch_daily(ts_code, start, end)   → 个股 70 日线 (×M)
```
