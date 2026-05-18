# 交易记录目录规划

## 目录结构

```text
trading-journal/
  trades.csv                    # 所有交易的结构化流水，一笔交易一行
  PLAN.md                       # 本目录使用说明
  trades/
    trade-template.md            # 单笔交易详细记录模板
  reviews/
    daily/
      daily-review-template.md   # 每日复盘模板
    weekly/
      weekly-review-template.md  # 每周复盘模板
```

## 使用规则

1. 每一笔交易先写入 `trades.csv`。
2. 需要详细复盘的交易，从 `trades/trade-template.md` 复制一份，命名为：

```text
YYYY-MM-DD-股票代码-交易编号.md
```

示例：

```text
2026-05-18-000001-T001.md
```

3. 每个交易日结束后，从 `reviews/daily/daily-review-template.md` 复制一份到 `reviews/daily/`，命名为：

```text
YYYY-MM-DD.md
```

4. 每周结束后，从 `reviews/weekly/weekly-review-template.md` 复制一份到 `reviews/weekly/`，命名为：

```text
YYYY-W周数.md
```

5. 没有记录的交易，视为无效样本，不纳入验证期统计。

## 验证期硬规则

```text
至少30笔交易或连续1-3个月
单票10%-20%仓位
单笔最大亏损不超过本金1%
市场评分低于6分不做实盘验证
连续亏损3笔暂停
账户从阶段高点回撤超过8%暂停
规则执行率低于90%不进入下一阶段
```
