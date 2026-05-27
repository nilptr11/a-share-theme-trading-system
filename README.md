# A 股主题选股扫描系统

> 文档驱动的 A 股主题选股扫描系统，包含交易规则、执行模板、Tushare 数据接口和每日扫描 CLI。代码主流程只做市场、主线、核心股、买点和卖点预案扫描，输出止损参考与观察/预案结果，不计算仓位。

## 快速入口

| 文件 | 用途 |
|------|------|
| [docs/trading-system/trading-reference.md](docs/trading-system/trading-reference.md) | 核心执行版，定义交易准入、主线判断、买点、仓位、卖出、暂停、成本和复盘边界 |
| [docs/trading-system/trading-templates.md](docs/trading-system/trading-templates.md) | 盘前、盘中、买入前、卖出后、复盘记录模板 |

## 常用命令

```bash
uv run daily-scan 20260523 --no-buy-points
uv run fetch-tushare-news --all
```

## 使用顺序

```text
先判断市场是否允许选股
再判断主线在哪里
只看主线核心强势股
只等标准买点
输出止损参考和失败信号
人工按交易模板完成仓位和复盘
```

## 核心原则

```text
人先判断方向，数字只做校准
市场评分不是买入信号，只是交易权限校准
主线判断不清楚，即使评分达标也不交易
```

```text
市场决定能不能做
主线决定看哪里
强弱决定选哪只
买点决定何时进
止损决定风险边界
纪律决定是否执行
```
