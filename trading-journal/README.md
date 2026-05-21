# 交易日志

> 本目录只负责记录交易数据，不定义交易规则。所有规则以 `../trading-system/trading-reference.md` 和 `../trading-system/trading-playbook.md` 为准。

## 文件说明

| 文件 | 用途 |
|------|------|
| [trades.csv](trades.csv) | 每笔交易的唯一必填流水，一笔交易一行 |
| [trades/trade-review-template.md](trades/trade-review-template.md) | 重点或异常交易的深度复盘模板 |
| [../trading-system/review-templates.md](../trading-system/review-templates.md) | 每日、每周、每 15 笔/月度复盘模板 |

## 记录规则

1. 每笔交易必须先写入 `trades.csv`。
2. 没有写入 `trades.csv` 的交易，不纳入复盘统计。
3. 每日、每周和每 15 笔/月度复盘，统一使用 `../trading-system/review-templates.md`。
4. 单笔 Markdown 复盘不是每笔必填，只用于重点或异常交易。

## 需要单独复盘的交易

出现以下任一情况，从 `trades/trade-review-template.md` 复制一份到 `trades/`：

```text
大亏交易
违反规则交易
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
