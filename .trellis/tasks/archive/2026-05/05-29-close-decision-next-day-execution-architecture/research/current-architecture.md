# Research: current architecture for close decision / next-day execution

- **Query**: 为“收盘后做决策，次日只做执行确认”的架构调整提供代码依据：1) 找出现有 signal/plan/execution 边界相关文件和数据流；2) 查找 trade_date、confirm_date、execution_date、pending_next_open、executable_plan 等状态如何使用；3) 标出当前可能混用扫描基准日/确认日/执行日的位置；4) 给出 2-3 个可落地架构方案及推荐。
- **Scope**: internal
- **Date**: 2026-05-29

## Findings

### Files Found

| File Path | Description |
|---|---|
| `src/theme_trading/cli/daily_scan.py` | CLI 入口，解析扫描日期并调用 `daily_scan(trade_date, ...)`。 |
| `src/theme_trading/cli/render_daily_scan.py` | 报告渲染层，展示待确认、可执行预案、试错预案，以及信号日/确认日/计划买入日。 |
| `src/theme_trading/scanner/daily_scan.py` | 每日扫描编排层：市场评分、主线、核心股、pending review、当前买点扫描、signal 构建和 route。 |
| `src/theme_trading/scanner/buy_points.py` | 个股买点扫描层：用 `trade_date` 定位行情行，生成 `setup_date`、`confirm_date`、`execution_date`，并提供 pending setup 确认函数。 |
| `src/theme_trading/scanner/buy_point_rules.py` | 买点规则与 execution check 层：计算次日开盘价相对确认收盘价的 gap，并产出 `pending_next_open` / `executable_plan` 等状态。 |
| `src/theme_trading/scanner/signals.py` | signal 构建层：把 buy scan / pending review 转换为 `TradeSignal`，附带风险预算和买前检查。 |
| `src/theme_trading/scanner/routing.py` | plan 路由层：把 signal 状态路由到 `executable_plans`、`trial_plans`、`pending_confirmations` 或阻断观察池。 |
| `src/theme_trading/scanner/pending.py` | pending setup 回看流程：用当前 `trade_date` 作为 confirm date 调用 `confirm_pending_buy_point`。 |
| `src/theme_trading/scanner/report.py` | Daily report 容器初始化：定义 `pending_confirmations`、`executable_plans`、`trial_plans`、`pending_reviews` 等输出槽位。 |
| `src/theme_trading/scanner/types.py` | TypedDict 数据契约：`BuyPointScanResult`、`TradeSignal`、`DailyScanReport` 中声明日期和状态字段。 |
| `src/theme_trading/scanner/utils.py` | 买点选择工具：定义可选择状态集合，包含 `executable_plan`、`pending_next_open`、`pending_next_day_strength`、`watch`。 |
| `src/theme_trading/scanner/market_score.py` | 市场扫描基准日使用者：按 `trade_date` 拉指数、涨跌停、全市场日线并检查数据新鲜度。 |
| `src/theme_trading/scanner/themes.py` | 主线扫描基准日使用者：按 `trade_date` 拉板块当日、指数、涨停、全市场日线和历史板块。 |
| `src/theme_trading/scanner/core_stocks.py` | 核心股扫描基准日使用者：按 `trade_date` 拉全市场日线、daily_basic 和历史行情。 |
| `src/theme_trading/data/market_data.py` | Tushare 数据访问层，`trade_date` 是各行情 API 的单日参数，`start_date/end_date` 是历史区间参数。 |
| `tests/test_signal_layering.py` | 现有测试覆盖 signal layering、watch shape 不 route、invalid setup 诊断、渲染等行为。 |

### Current Data Flow and Boundaries

#### 1. CLI → daily report

- `src/theme_trading/cli/daily_scan.py:39-49` 将 CLI 参数命名为 `trade_date`，默认来自 `find_latest_trade_date()`，然后直接传给 `daily_scan(...)`：

```python
trade_date = args.date or find_latest_trade_date()
report = daily_scan(
    trade_date,
    sector_codes=None,
    theme_top_n=args.sectors,
    include_buy_points=not args.no_buy_points,
)
```

- 入口层没有区分“扫描基准日 / 收盘决策日 / 执行确认日”。当前所有下游模块收到的都是同一个 `trade_date`。

#### 2. daily_scan 编排层

- `src/theme_trading/scanner/daily_scan.py:15-21` 的唯一日期入参是 `trade_date`。
- `daily_scan` 依次调用：
  - `compute_market_score(trade_date)`：`daily_scan.py:26`
  - `find_main_themes(trade_date, ...)`：`daily_scan.py:38`
  - `filter_core_stocks(trade_date, sector_codes)`：`daily_scan.py:65`
  - `review_pending_setups(..., trade_date=trade_date, ...)`：`daily_scan.py:101-109`
  - `_scan_current_buy_points(..., trade_date=trade_date, ...)`：`daily_scan.py:111-119`

这说明现有 pipeline 的 `trade_date` 同时承担：市场/主线/核心股扫描基准日、pending setup 确认日、当前买点 setup/confirm 基准日。

#### 3. market / theme / core scan

- `src/theme_trading/scanner/market_score.py:78-106` 用 `trade_date` 拉指数历史到当天；`market_score.py:110-115` 检查指数最新日期是否等于扫描日期；`market_score.py:204-205` 用 `trade_date` 拉涨跌停和最强板块；`market_score.py:262` 用 `trade_date` 拉全市场日线。
- `src/theme_trading/scanner/themes.py:100-145` 用 `trade_date` 拉当日板块、指数、涨停、全市场日线；`themes.py:155` 拉板块历史到 `trade_date`。
- `src/theme_trading/scanner/core_stocks.py:247-266` 用 `trade_date` 拉全市场当日、daily_basic、近 45 日历史。

这些层的 `trade_date` 语义比较一致：扫描基准日 / 收盘数据日期。

#### 4. buy scan 层

- `src/theme_trading/scanner/buy_points.py:37-47` 的 `scan_buy_points(ts_code, trade_date, ...)` 将入参 `trade_date` 作为定位行情行的日期，但会向后多拉 10 个自然日：

```python
start = _n_days_ago(trade_date, 90)
end = _n_days_after(trade_date, 10)
df = fetch_daily(ts_code=ts_code, start_date=start, end_date=end)
```

- `buy_points.py:51-62` 找到 `df["trade_date"] == trade_date` 的行作为 `today`，然后直接取 `next_row` 和 `next_next_row`：

```python
confirm_matches = df.index[df["trade_date"] == trade_date].tolist()
today = confirm_matches[0]
next_row = df.iloc[today + 1] if today + 1 < len(df) else None
next_next_row = df.iloc[today + 2] if today + 2 < len(df) else None
hist = df.iloc[:today + 1].copy()
```

- 初始化结果时，`trade_date` 与 `setup_date` 被赋同一个值，`confirm_date/execution_date` 先为空：`buy_points.py:82-88`。
- 每个买点信息的日期赋值在 `buy_points.py:165-169`：
  - 买点一：`confirm_date = trade_date`，`execution_date = next_row.trade_date` 或 `None`。
  - 买点二/三/四：`confirm_date = next_row.trade_date`，`execution_date = next_next_row.trade_date`。
- 选中买点后的顶层日期赋值在 `buy_points.py:178-184`，同样按“买点一当天确认、其它买点次日确认”处理。

因此，当前 `scan_buy_points` 同时做了：
1. 收盘 setup 识别；
2. 次日转强确认（买点二/三/四）；
3. 次日或次次日开盘 gap 执行条件检查（如果未来行情行存在）。

#### 5. execution check / status 层

- `src/theme_trading/scanner/buy_point_rules.py:125-135` 的 `execution_check(confirm_close, next_row)` 读取 `next_row["open"]` 并返回：`confirm_close`、`next_trade_date`、`next_open`、`gap_limit_pct`、`gap_check`、执行规则文案。
- `src/theme_trading/scanner/buy_point_rules.py:146-165` 的 `status_for_setup(...)` 将 setup、strength、gap 三者揉在一起产出状态：
  - `not_triggered`：setup 不成立；
  - `watch`：被 blocked；
  - `invalid`：gap 已检查但失败，或转强失败；
  - `pending_next_day_strength`：需要转强但 `strength_ok is None`；
  - `pending_next_open`：setup/转强成立，但 gap 尚未检查；
  - `executable_plan`：setup/转强成立，gap 已检查且通过。

关键代码：

```python
if needs_strength:
    if strength_ok is None:
        return False, "pending_next_day_strength", execution
    if not strength_ok:
        return False, "invalid", execution
    if not gap["checked"]:
        return True, "pending_next_open", execution
    return True, "executable_plan", execution
if not gap["checked"]:
    return True, "pending_next_open", execution
return True, "executable_plan", execution
```

这说明 `pending_next_open` 与 `executable_plan` 的差异只在“开盘 gap 是否已经可检查”。

#### 6. signal 构建层

- `src/theme_trading/scanner/signals.py:86-118` 把 `buy_scan` 和选中的 `buy_point_info` 复制成 `TradeSignal`。日期来源为：
  - `setup_date`: `buy_scan.get("setup_date")`
  - `confirm_date`: `info.get("confirm_date", buy_scan.get("confirm_date"))`
  - `execution_date`: `info.get("execution_date", buy_scan.get("execution_date"))`
  - `close`: `info.execution_check.confirm_close` 优先，否则 `buy_scan.close`
- `signals.py:43-73` 对 pending review 构建 signal 时同样复制 `setup_date/confirm_date/execution_date/execution_check/status`。
- `_attach_risk_and_checklist` 在 `signals.py:19-39` 同时附加 `risk_budget_for_plan` 和 `pre_trade_checklist`。这一步发生在 signal 构建时，而不是执行日单独确认时。

#### 7. routing / plan 层

- `src/theme_trading/scanner/routing.py:6-11` 将买点状态分三类：
  - `executable_plan`、`pending_next_open` → `ready`
  - `pending_next_day_strength`、`watch` → `pending`
  - 其它 → `blocked`

```python
if bp_status in ("executable_plan", "pending_next_open"):
    return "ready"
```

- `src/theme_trading/scanner/routing.py:38-47` 对 `ready` 状态直接加入 `executable_plans` 或 `trial_plans`。因此当前 `pending_next_open` 已被视作可进入“可执行预案”列表。
- `route_signal` 还会先检查 `market_closed` 和 `pre_trade_check`：`routing.py:23-36`。买前检查不通过的 signal 不会进入 plan，而是进入 `observation_pool`。

#### 8. pending review 层

- `src/theme_trading/scanner/pending.py:12-21` 的 `review_pending_setups(..., trade_date, ...)` 将当前 `trade_date` 作为 pending setup 的确认日期使用。
- `pending.py:51-59` 调用：

```python
review = confirm_pending_buy_point(
    ts_code,
    setup_date,
    trade_date,
    buy_point_name,
    market_context=stock_score,
    sector_context=sector_context,
    core_context=stock,
)
```

- `src/theme_trading/scanner/buy_points.py:189-205` 的 `confirm_pending_buy_point(ts_code, setup_date, confirm_date, ...)` 实际调用 `scan_buy_points(ts_code, setup_date, ...)`，即以 setup date 重跑买点扫描，然后比较 `actual_confirm_date` 与传入的 `confirm_date`：`buy_points.py:229-240`。

这说明 pending review 的确认日来自 daily scan 的 `trade_date`，但买点扫描本体仍以 `setup_date` 为基准，并依赖 `scan_buy_points` 向后读取的 `next_row/next_next_row`。

#### 9. report / render 层

- `src/theme_trading/scanner/report.py:6-24` 初始化 report，顶层只有 `trade_date`，没有 `decision_date` 或 `execution_date` 顶层字段。
- `src/theme_trading/cli/render_daily_scan.py:218-239` 展示 plan 时使用“信号日 → 确认日 → 计划买入日”：

```python
dates = f"信号日 {item.get('setup_date') or '-'}  →  确认日 {item.get('confirm_date') or '-'}  →  计划买入日 {item.get('execution_date') or '-'}"
```

- 渲染层不区分 `pending_next_open` 和 `executable_plan` 所在列表；两者都可能出现在“可执行预案”标题下，因为 routing 已将它们都归为 ready。

### How Key Dates and States Are Used

#### `trade_date`

当前含义分布：

| 使用位置 | 现有语义 |
|---|---|
| CLI `daily_scan.py:39-45` | 用户输入 / 默认最近交易日。 |
| report `report.py:6-8` | Daily report 顶层日期。 |
| market score `market_score.py:78-319` | 市场扫描基准日。 |
| theme scan `themes.py:100-262` | 主线扫描基准日。 |
| core stock scan `core_stocks.py:247-384` | 核心股扫描基准日。 |
| buy scan `buy_points.py:37-62` | 定位个股 setup/确认基准行；买点一的确认日；买点二/三/四的 setup 日。 |
| pending review `pending.py:16-55` | 传给 `confirm_pending_buy_point` 的确认日。 |
| data access `market_data.py` | Tushare 单日行情 API 参数。 |

#### `setup_date`

- `src/theme_trading/scanner/buy_points.py:85-86` 当前默认等于 `trade_date`。
- `src/theme_trading/scanner/signals.py:60` 和 `signals.py:106` 将其复制到 signal。
- `src/theme_trading/scanner/pending.py:28-29` 要求 pending setup 输入必须有 `setup_date`。

#### `confirm_date`

- `src/theme_trading/scanner/buy_points.py:168`：买点一为 `trade_date`；买点二/三/四为 `next_row.trade_date`。
- `src/theme_trading/scanner/buy_points.py:180-184`：顶层选中买点同样赋值。
- `src/theme_trading/scanner/buy_points.py:229-240`：pending review 比较 `actual_confirm_date` 与传入 `confirm_date`，不相等则返回 `pending_next_day_strength`。
- `src/theme_trading/scanner/signals.py:61`、`signals.py:107`：signal 复制该字段。
- `src/theme_trading/cli/render_daily_scan.py:224`：展示为“确认日”。

#### `execution_date`

- `src/theme_trading/scanner/buy_points.py:169`：买点一为 `next_row.trade_date`；买点二/三/四为 `next_next_row.trade_date`。
- `src/theme_trading/scanner/buy_points.py:181-184`：顶层选中买点同样赋值。
- `src/theme_trading/scanner/signals.py:62`、`signals.py:108`：signal 复制该字段。
- `src/theme_trading/cli/render_daily_scan.py:224`：展示为“计划买入日”。
- 当前没有独立 execution module；`execution_date` 只是 buy scan / signal 的数据字段，没有单独的“执行确认输入/输出”对象。

#### `pending_next_open`

- `src/theme_trading/scanner/buy_point_rules.py:160-165`：setup 成立但 `execution_check.gap_check.checked == False` 时返回。
- `src/theme_trading/scanner/utils.py:97-102`：属于可选择买点状态。
- `src/theme_trading/scanner/routing.py:6-8`：被归为 `ready`，会进入 `executable_plans` 或 `trial_plans`。
- `src/theme_trading/scanner/daily_scan.py:160`：观察主线买点形态也会收集该状态。
- `src/theme_trading/scanner/buy_point_rules.py:193`：强度评分认为它“已进入可计划状态”。

#### `executable_plan`

- `src/theme_trading/scanner/buy_point_rules.py:162` 和 `165`：setup/转强成立且开盘 gap 已检查并通过时返回。
- `src/theme_trading/scanner/utils.py:97-102`：属于可选择买点状态。
- `src/theme_trading/scanner/routing.py:6-8`：被归为 `ready`，进入 plan 列表。
- `src/theme_trading/scanner/buy_point_rules.py:193`：强度评分认为它“已进入可计划状态”。

### Current Places Where Scan Date / Confirm Date / Execution Date May Be Mixed

1. **`scan_buy_points` 的 `trade_date` 命名与实际职责混合**
   - 位置：`src/theme_trading/scanner/buy_points.py:37-62`、`buy_points.py:165-184`。
   - 现象：函数名和参数叫 `trade_date`，但结果里同时生成 `setup_date`、`confirm_date`、`execution_date`。买点一的 `trade_date` 是确认日，买点二/三/四的 `trade_date` 是 setup 日。
   - 影响边界：同一个参数既是收盘扫描基准日，又是某些买点的 setup 日；确认和执行由向后读取的行情推导。

2. **`scan_buy_points` 向后拉 10 个自然日，可能在回放/历史场景提前做未来确认和执行检查**
   - 位置：`src/theme_trading/scanner/buy_points.py:45-47`。
   - 现象：只要数据源包含 `trade_date` 之后的行情，`next_row`/`next_next_row` 就会参与转强确认和开盘 gap 检查。
   - 对“收盘后做决策，次日只做执行确认”的相关性：收盘决策阶段若用历史日期运行，可能直接得到 `executable_plan`，而不是保留为 `pending_next_open`；执行确认逻辑没有与决策阶段隔离。

3. **`execution_check` 在买点规则内部执行，而不是执行日独立阶段执行**
   - 位置：`src/theme_trading/scanner/buy_point_rules.py:125-165`。
   - 现象：状态机在买点规则层直接读取 next open 并决定 `pending_next_open` 或 `executable_plan`。
   - 边界：signal 生成前已经混入执行日开盘条件；没有单独的 execution confirmation 输入。

4. **`pending_next_open` 被 route 为 ready plan**
   - 位置：`src/theme_trading/scanner/routing.py:6-8`、`routing.py:38-44`。
   - 现象：`pending_next_open` 和 `executable_plan` 都进入 `executable_plans` / `trial_plans`。
   - 边界：输出列表名“可执行预案”包含“尚待次日开盘确认”的 plan。当前语义更接近“已形成次日执行预案”，而不是“已通过执行确认”。

5. **pending review 的确认日来自当前 daily scan，但买点扫描上下文来自 setup date，市场/板块/核心上下文来自当前 date**
   - 位置：`src/theme_trading/scanner/pending.py:51-59`、`src/theme_trading/scanner/buy_points.py:199-205`。
   - 现象：`confirm_pending_buy_point(ts_code, setup_date, confirm_date, market_context=当前score, sector_context=当前theme, core_context=当前stock)` 内部调用 `scan_buy_points(ts_code, setup_date, ...)`。价格形态基于 setup date 及其未来行，市场/板块/核心 context 则由当前 `trade_date` 的 daily scan 得出。
   - 边界：对 pending setup 来说，价格序列基准日、确认日、上下文日期分属不同含义，但接口没有显式表达。

6. **report 顶层只有 `trade_date`，没有 decision/execution phase 元数据**
   - 位置：`src/theme_trading/scanner/report.py:6-24`、`src/theme_trading/scanner/types.py:123-140`。
   - 现象：DailyScanReport 顶层仅 `trade_date`。计划列表中的 `execution_date` 是局部字段。
   - 边界：无法从 report schema 判断本报告是“收盘决策产物”还是“次日执行确认产物”。

7. **`execution_check.next_trade_date` 与 signal `execution_date` 是并列但未强约束的一组字段**
   - 位置：`src/theme_trading/scanner/buy_point_rules.py:129-135`、`src/theme_trading/scanner/signals.py:107-111`。
   - 现象：`execution_check` 内部有 `next_trade_date`，signal 顶层有 `execution_date`，二者都从 next row 推导，但 type contract 未表达一致性要求。
   - 边界：未来若单独执行确认，需要明确哪个是 authoritative execution date。

8. **CLI 默认最近交易日不保证是“已收盘数据完整日”**
   - 位置：`src/theme_trading/cli/daily_scan.py:12-26`。
   - 现象：`find_latest_trade_date()` 用交易日历返回最近开市日；如果盘中运行，也可能返回当天。
   - 边界：对“收盘后做决策”的架构，入口层需要明确“决策日期必须是已收盘且数据完整”的日期；当前没有 phase 或数据完整性 gate。

### Existing Tests Relevant to These Boundaries

- `tests/test_signal_layering.py:106-148` 验证 `build_signal_from_buy_scan` 会复制 strength 字段。
- `tests/test_signal_layering.py:211-266` 验证观察主线买点形态不进入 route，不产生 `executable_plans`/`trial_plans`。
- `tests/test_signal_layering.py:325-374` 验证 watch shape 会携带 `confirm_date`、`execution_date`、`execution_check` 等字段。
- `tests/test_signal_layering.py:446-496` 验证 invalid setup 会进入观察诊断，且不会 route。
- `tests/test_signal_layering.py:498-543` 验证 render 会展示 invalid setup execution gap 诊断。

### Related Specs

| Spec Path | Finding |
|---|---|
| `.trellis/spec/backend/index.md` | 当前是模板性 backend guidelines，未记录 signal/plan/execution 日期语义。 |
| `.trellis/spec/backend/directory-structure.md` | 当前是待填模板，未记录 scanner 分层约定。 |
| `.trellis/spec/guides/index.md` | 存在 guides 目录，但本次未发现与当前日期/执行架构直接对应的规范。 |

### External References

- None. 本次任务是当前项目内部架构研究，未做外部搜索。

## Architecture Options

### 方案 A：最小改动，显式把 `pending_next_open` 定义为“收盘决策完成、次日待执行确认”

**核心做法**

- 保留现有 `daily_scan(trade_date)` 主流程和 report shape。
- 明确状态语义：
  - `pending_next_open` = close decision 已完成，plan 已生成，但 execution confirmation 尚未做；
  - `executable_plan` = 已检查次日开盘 gap，通过执行确认。
- 在输出上把 `executable_plans` 改名或补充展示语义，例如“次日执行预案 / 待开盘确认”，避免把 `pending_next_open` 表述为已可执行。
- 增加一个轻量 execution confirmation 函数，输入 close decision 产物中的 plan + 次日开盘行情，只更新 `execution_check` 和 status。

**落地点**

- `routing.py:6-8` 已经把 `pending_next_open` route 到 ready，可延续现有行为。
- `render_daily_scan.py:218-239` 是主要展示调整点。
- `buy_point_rules.execution_check` 可复用为执行确认逻辑。

**优点**

- 对现有 pipeline 侵入小。
- 兼容当前 `pending_next_open` 已进入 `executable_plans` 的事实。
- 适合先把业务语言从“可执行”校正为“执行预案”。

**不足**

- `scan_buy_points` 仍会在有未来数据时直接产出 `executable_plan`，决策阶段和执行确认阶段没有硬隔离。
- 日期语义仍主要靠约定，而不是接口约束。

### 方案 B：中等改动，拆出 Close Decision 与 Open Execution Confirmation 两个显式 phase

**核心做法**

- 将收盘决策阶段定义为只接受 `decision_date` / `as_of_date`，禁止读取 decision date 之后的行情参与执行确认。
- Close Decision 阶段输出 `DecisionPlan`：包含 `setup_date`、`confirm_date=decision_date`、`planned_execution_date`、`status=pending_next_open`、`confirm_close`、止损、失败信号、risk budget、pre-trade checklist。
- 次日执行确认阶段新增 `confirm_execution(plan, execution_date)`：读取 execution date 开盘价，检查 gap，输出 `ExecutableOrderDecision` 或 `invalid`。
- `executable_plan` 状态只允许由 execution phase 产生；close decision phase 不再产出 `executable_plan`。

**落地点**

- `buy_points.py:45-62`：收盘决策扫描需要禁止/忽略 `next_row.open`，或增加参数控制是否允许 future rows。
- `buy_point_rules.py:125-165`：把 `execution_check` 从买点规则中抽出为可由 execution phase 调用；买点规则只产出 setup/confirm 结果。
- `routing.py:6-8`：close decision route 可将 `pending_next_open` 放入“execution_plans / next_open_plans”；execution phase route 才产生 `executable_plan`。
- `types.py:66-120`：补充 phase/decision/execution 字段，或新增 TypedDict。
- `render_daily_scan.py:218-239`：展示“决策日 / 计划执行日 / 执行确认状态”。

**优点**

- 与目标“收盘后做决策，次日只做执行确认”语义匹配。
- 可以避免历史回放时 close decision 阶段偷看未来开盘。
- 让 `executable_plan` 的含义更单一：已通过开盘执行确认。

**不足**

- 需要调整状态机和测试。
- pending setup 的买点二/三/四“次日转强确认”仍需单独定义属于 decision phase 还是 confirmation phase：如果转强确认发生在收盘后，则它应是 close decision；如果盘中确认，则需更细分。

### 方案 C：较大改动，引入 Plan Store / Pending Queue，daily scan 只产出持久化计划，执行命令只消费计划

**核心做法**

- Close scan 只生成并持久化 `plans`：`plan_id`、`decision_date`、`setup_date`、`confirm_date`、`planned_execution_date`、`status=pending_next_open`、信号快照、上下文快照。
- Next-day execution command 读取 plan store 中 `planned_execution_date == execution_date` 且 `status=pending_next_open` 的计划，仅做 open gap / checklist freshness / status update。
- pending setup queue 与 next open plan queue 分开：
  - `pending_next_day_strength`：等待收盘转强确认；
  - `pending_next_open`：等待开盘执行确认。

**落地点**

- 当前没有数据库或 plan store；`report.py` 只是内存 dict。需要新增文件存储或轻量 JSON 数据层。
- `pending.py` 可演进为 pending queue review。
- `cli/daily_scan.py` 可能新增 `close-decision` 与 `execute-open` 两个命令入口。

**优点**

- 最符合可运行交易流程：决策产物可审计、可复盘、可在次日消费。
- 最清晰地区分“观察/等待转强/等待开盘执行/已通过/已失效”。

**不足**

- 改动范围最大，需要定义持久化格式、迁移测试和 CLI 用户流程。
- 当前项目暂未发现数据库/持久化交易计划基础设施。

## Recommendation

推荐采用 **方案 B 作为主线，方案 A 的展示语义修正作为第一步落地**。

依据：当前代码已经有 `pending_next_open`、`execution_check`、`execution_date`、`route_signal` 等基础构件，说明系统已隐含“收盘计划 + 次日开盘确认”的模型；但 `scan_buy_points` 会向后读取未来行情并在买点规则内直接执行 gap check，导致 close decision 与 execution confirmation 没有硬边界。方案 B 可以在不立即引入 plan store 的前提下，把 phase 和日期语义先拆清楚：收盘决策只生成 `pending_next_open` 计划，次日执行确认才把它升级为 `executable_plan` 或置为 `invalid`。

建议落地顺序：

1. **先固化命名和契约**：在 types/report 中增加或明确 `decision_date`、`planned_execution_date`、`execution_status`，并约定 close decision 不产出已确认的 `executable_plan`。
2. **拆 execution check 调用时机**：让 close decision 阶段不使用 `next_row.open`；把 `execution_check(confirm_close, execution_open_row)` 留给 next-day execution confirmation。
3. **调整 routing/render**：`pending_next_open` 输出为“次日执行预案/待开盘确认”，`executable_plan` 只在执行确认通过后出现。
4. **后续如需自动化交易流程，再升级到方案 C**：引入 plan store / pending queue，让次日命令消费前一日计划。

## Caveats / Not Found

- 未发现独立 execution module 或订单执行层；当前 execution 只是买点规则里的 `execution_check` 和 report/signal 字段。
- 未发现持久化 plan store；pending setups 通过 `daily_scan(..., pending_setups=...)` 参数传入，CLI 当前未暴露该参数。
- `.trellis/spec/backend/*` 目前多为模板内容，未找到关于日期语义或 signal/plan/execution 边界的项目规范。
- 当前代码使用自然日 `_n_days_after` 作为查询 end date 扩展，但实际 `next_row` 来自行情 DataFrame 的下一条交易记录；若需要计划买入日，即使 close decision 阶段不读取 next row，也可能需要交易日历来计算下一交易日。
