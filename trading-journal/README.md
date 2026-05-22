# 交易日志

> 本目录只负责记录交易数据，不定义交易规则。所有规则以 `../trading-system/trading-reference.md` 为准。

## 文件说明

| 文件 | 用途 |
|------|------|
| [trades.csv](trades.csv) | 每笔交易的唯一必填流水，一笔交易一行 |
| [trades/trade-review-template.md](trades/trade-review-template.md) | 重点或异常交易的深度复盘模板 |
| [../trading-system/review-templates.md](../trading-system/review-templates.md) | 每日、每周和定期复盘模板 |

## 记录规则

1. `trades.csv` 只记录交易事实，不定义交易规则。
2. 交易前的市场状态、风险预算、计划股数和预估成本属于执行风控信息。
3. 卖出后的实际成本、扣成本后盈亏和错误类型属于复盘信息。
4. 每日、每周和定期复盘，统一使用 `../trading-system/review-templates.md`。
5. 单笔 Markdown 复盘不是每笔必填，只用于重点或异常交易。
6. 记录缺失只影响复盘质量，不反向改变 `../trading-system/trading-reference.md` 的规则口径。

## 需要单独复盘的交易

出现以下任一情况，从 `trades/trade-review-template.md` 复制一份到 `trades/`：

```text
大亏交易
超过计划风险的交易
违反规则交易
状态 B 使用 6.3 的交易
市场评分 < 6 却实盘的交易
典型盈利交易
标准模型样本
情绪失控交易
```

命名格式：

```text
YYYY-MM-DD-股票代码-交易编号.md
```

示例：

```text
2026-05-18-000001-T001.md
```
