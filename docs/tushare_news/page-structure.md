# 页面结构

- 标题：Tushare数据
- keywords：免费股票数据,开源股票数据接口,股票数据,股票数据接口,python股票数据,财经数据,金融数据,行业大数据,区块链数据,量化投资,知识图谱
- description：Tushare为金融数据分析提供便捷、快速的接口，与投研和量化策略无缝对接
- 搜索控件：存在，选择器为 `#search-input` 和 `#search-button`。

## 主导航

| 文案 | URL |
| --- | --- |
| 首页 | https://tushare.pro/ |
| 平台介绍 | https://tushare.pro/document/1 |
| 数据接口 | https://tushare.pro/document/2 |
| 资讯数据 | https://tushare.pro/news/sina |
| 数据工具 | https://tushare.pro/webclient |
| 权限中心 | https://tushare.pro/weborder/#/permission |
| 1 | https://tushare.pro |
| 个人中心 | https://tushare.pro/weborder/#/user/privilege |
| 退出登录 | https://tushare.pro |

## 资讯源导航

| 来源 | slug | URL |
| --- | --- | --- |
| 雪球 | `xq` | https://tushare.pro/news/xq |
| 第一财经 | `yicai` | https://tushare.pro/news/yicai |
| 凤凰 | `fenghuang` | https://tushare.pro/news/fenghuang |
| 同花顺 | `10jqka` | https://tushare.pro/news/10jqka |
| 金融界 | `jinrongjie` | https://tushare.pro/news/jinrongjie |
| 新浪财经 | `sina` | https://tushare.pro/news/sina |
| 云财经 | `yuncaijing` | https://tushare.pro/news/yuncaijing |
| 财联社 | `cls` | https://tushare.pro/news/cls |
| 东方财富 | `eastmoney` | https://tushare.pro/news/eastmoney |
| 华尔街见闻 | `wallstreetcn` | https://tushare.pro/news/wallstreetcn |

## 可复用解析选择器

| 内容 | 选择器/规则 |
| --- | --- |
| 来源导航 | `#data_source_head span.source_name a` |
| 当前来源 | `span.source_name.cur` |
| 搜索框 | `#search-input` |
| 搜索按钮 | `#search-button` |
| 频道名称 | `#channel_head .channel_name` |
| 频道内容容器 | `id="news_{频道名}"`，需用 id 精确查找，不能直接拼 CSS 选择器，因为频道名可能含 `*` |
| 新闻条目 | `.news_item` |
| 发布时间 | `.news_datetime` |
| 正文 | `.news_content` |
