# 收盘决策、次日执行架构调整

## Goal

将当前 A 股主题交易系统的架构明确调整为“收盘后做决策，次日只做执行确认”：所有信号确认只使用已经收盘并完成落库的完整交易日数据，新的交易日不做临时买点分析和追入，只对已生成计划做执行可行性确认。这样避免当天不完整数据污染信号，也为后续板块轮动检测、阈值配置化和回测验证铺路。

## What I already know

* 用户确认当前数据约束不是“只能拿到前一天完整数据”，而是“只能拿到今天以前、已经收盘并完成落库的交易日完整数据；今天到收盘前都不完整”。
* 用户认可系统应采用“收盘后做决策，次日只做执行确认”，而不是盘中临时分析、临时追入。
* 当前文档已有“所有买点依赖收盘数据确认，确认日次日开盘执行，次日开盘价相对确认日收盘价 ±3% 内才可执行”的规则。
* 当前代码已有 `confirm_date`、`execution_date`、`pending_next_open`、`executable_plan`、`invalid` 等状态雏形。
* 当前架构仍需要更清晰地区分 signal / plan / execution check 边界。

## Assumptions (temporary)

* 当前项目仍处于开发阶段，可以接受大幅重构和破坏性内部接口调整。
* 架构调整应优先追求日期语义、阶段边界和数据流清晰，而不是维持旧内部接口兼容。
* 本任务先做架构规划和边界设计，不立即实现全部轮动检测、阈值校准和回测系统。
* 若进入实现，优先保证不完整当日数据不能进入信号确认层。
* 执行确认可以使用执行日开盘/盘前可得数据，但只能用于过滤计划，不能生成新信号。

## Open Questions

* 暂无阻塞问题；待用户确认完整实施计划。

## Research References

* [`research/current-architecture.md`](research/current-architecture.md) — 当前代码已有 `pending_next_open`、`execution_check`、`execution_date` 等雏形，但 close decision 与 open execution confirmation 没有硬隔离。

## Feasible Approaches

### Approach A: 最小语义修正

* 保留现有 `daily_scan(trade_date)` 主流程。
* 明确 `pending_next_open` 表示“次日执行预案，待开盘确认”，调整渲染文案。
* 优点：改动小。
* 缺点：`scan_buy_points` 在历史回放时仍可能读取未来开盘并直接产出 `executable_plan`。

### Approach B: 显式拆分收盘决策与开盘执行确认（推荐）

* Close Decision 阶段只用 `decision_date/latest_complete_trade_date` 及之前数据，产出人工执行预案，状态为 `pending_next_open`。
* Open Execution Confirmation 阶段读取计划执行日开盘数据，只更新 gap/execution status。
* `executable_plan` 只允许由执行确认阶段产生。
* 允许大幅调整内部接口、类型和文件边界，以清晰表达 `signal -> decision_plan -> execution_confirmation`。
* 优点：边界清晰，避免偷看未来，便于后续回测复用。
* 缺点：需要调整状态机、类型、渲染和测试。

### Approach C: 引入计划持久化与人工执行预案清单

* 收盘扫描持久化 plan，次日执行确认命令消费 plan store。
* 区分 pending setup queue 与 next-open execution queue。
* 优点：最接近真实交易流程，可审计。
* 缺点：改动最大，需要新增持久化格式和 CLI 流程。

## Requirements (evolving)

* 引入或统一 `latest_complete_trade_date` 作为所有信号扫描的基准日期。
* 明确 signal / plan / execution check 三层职责。
* 买点是否成立只能由完整收盘数据决定。
* 次日执行确认只能判断既有计划是否还能执行，不能临时生成新买点。
* 设计应兼容周末、节假日、收盘后运行、数据延迟落库。
* 设计应为后续轮动检测、阈值配置化、回测验证预留清晰接入点。
* 收盘决策阶段应保存 JSON 人工执行预案文件，例如 `plans/YYYYMMDD.json` 或等价项目内路径。
* 次日执行确认阶段应读取前一收盘决策生成的 JSON 预案文件，检查开盘执行条件，并输出确认结果；系统不自动下单。
* CLI 入口采用复用现有 `daily-scan` 的方式：通过新增参数支持保存 plan JSON 和确认 open execution，避免新增过多命令。
* 推荐命令形态为 `daily-scan --date <decision_date> --save-plan` 与 `daily-scan --confirm-open --plan <plan.json>`，具体参数名可在实现时按现有 CLI 风格微调。
* 次日执行确认默认从现有数据源自动读取计划执行日的 open/交易状态数据，减少人工输入。
* 本次架构调整中，脚本不需要大模型输入，也不消费 LLM 对新闻的判断。
* 脚本层只负责确定性的收盘决策、JSON 人工执行预案生成、次日开盘执行确认。
* `data/tushare-news` 下的每日时讯数据暂由未来 Skill/大模型编排层读取和解释，不进入本次脚本 MVP。
* 长期目标是让本系统成为大模型可执行的交易决策逻辑/Skill：脚本输出结构化计划与确认结果，Skill 可额外读取 `data/tushare-news` 并结合时讯给用户做人工辅助判断。
* JSON 人工执行预案文件是只读收盘决策快照，次日执行确认不得回写修改该文件。
* JSON 人工执行预案文件应保存完整决策快照，包括市场评分、主线、板块、核心股理由、买点强度、失败条件、风险预算、执行条件等，用于复盘、审计和后续回测。
* 次日执行确认结果应单独输出为 confirmation JSON 或等价独立报告，保留原始计划可审计性。
* 本次同步调整文档和 CLI 文案：避免把收盘决策写成“次日开盘买入”，统一表达为“次日进入人工执行确认窗口”。
* CLI 输出应区分“待开盘确认预案”和“已通过开盘确认，可人工执行”。

## Acceptance Criteria (evolving)

* [ ] 架构方案明确说明 `latest_complete_trade_date` 如何确定和传递。
* [ ] 架构方案明确说明 signal / plan / execution check 的输入、输出和禁止事项。
* [ ] 架构方案能解释盘中运行时为什么不会用当天不完整 K 线确认买点。
* [ ] 架构方案覆盖买点一和需要次日转强确认的买点二/三/四。
* [ ] 架构方案说明与后续回测复用的关系。
* [ ] 收盘决策运行后会产生可审计的 JSON 人工执行预案文件。
* [ ] plan JSON 包含完整决策快照，足以支持人工复盘，不依赖重新查询当日上下文。
* [ ] 次日执行确认可以读取 JSON 预案文件并输出可人工执行/跳过/失效原因。
* [ ] 执行确认不会修改原始 plan JSON，而是生成独立 confirmation 输出。
* [ ] 文档和 CLI 输出不再把计划表述为“次日开盘必买”，而是表述为“次日人工执行确认”。
* [ ] CLI 输出能区分待确认计划和已通过确认的可人工执行项。

## Definition of Done (team quality bar)

* Tests added/updated if implementation changes behavior.
* Lint / typecheck / relevant test suite green if implementation begins.
* Docs updated if trading rules or CLI output behavior changes.
* Rollout/rollback considered if changing existing scan output schema.

## Out of Scope (explicit)

* 本任务不直接完成完整历史回测框架。
* 本任务不直接完成阈值自动校准/参数寻优。
* 本任务不直接完成完整板块轮动交易策略。
* 本任务不直接实现网页抓取型时讯分析或大模型新闻判断，只预留结构化接入边界。
* 本任务不引入实时盘中交易系统。
* 本任务不做自动下单、自动交易或无人值守执行。
* 本任务不引入“自动人工执行预案清单”；若需要保存计划，也只是面向用户的人工执行预案清单。

## Technical Approach

采用大幅重构但不自动交易的方案：把现有扫描流程拆成 `Signal -> DecisionPlan -> ExecutionConfirmation`。

* Close Decision 阶段以 `latest_complete_trade_date/decision_date` 为唯一完整数据边界，只使用该日期及以前的行情生成信号和人工执行预案。
* 收盘决策输出只读 plan JSON，保存完整决策快照；状态为 `pending_next_open` 或等待后续完整收盘日确认的 `pending_next_day_strength`。
* Open Execution Confirmation 阶段读取 plan JSON，默认从现有数据源获取计划执行日 open/交易状态，只判断预案是否仍可人工执行，输出独立 confirmation JSON。
* `executable_plan` 只表示“已通过开盘执行确认，可由用户人工执行”，不再由收盘决策阶段直接产生。
* 脚本层不消费大模型/新闻判断；未来 Skill 可读取 `data/tushare-news` 和脚本 JSON 输出，组合成面向用户的辅助判断。

## Decision (ADR-lite)

**Context**: 当前系统已隐含确认日、执行日、跳空检查等概念，但 `trade_date` 混用扫描基准日/确认日/执行日，且买点扫描会在有未来数据时直接做执行检查，不利于“收盘决策、次日确认”和回测复用。

**Decision**: 在开发阶段允许大幅重构，优先建立清晰阶段边界；引入只读 plan JSON 和独立 confirmation JSON；复用 `daily-scan` CLI 增加保存计划与开盘确认参数；不做自动下单，不把大模型或新闻判断接入脚本状态机。

**Consequences**: 内部接口、类型、路由、渲染和测试需要较大调整；但日期语义会更清晰，未来轮动检测、阈值配置、回测和 Claude Skill 编排更容易接入。

## Implementation Plan (small PRs)

* PR1: 类型与阶段边界重构。引入/整理 `DecisionPlan`、`ExecutionConfirmation`、`decision_date`、`planned_execution_date` 等契约，拆清 signal/plan/execution 状态语义。
* PR2: 收盘决策 plan JSON。让 `daily-scan --save-plan` 生成只读完整决策快照，确保收盘阶段不会使用计划执行日 open 做确认。
* PR3: 开盘执行确认。实现 `daily-scan --confirm-open --plan <plan.json>`，读取 open/交易状态，生成独立 confirmation JSON，不修改 plan JSON。
* PR4: 文档、CLI 文案和测试。统一术语为“人工执行确认”，更新交易文档、渲染输出和相关测试。

## Technical Notes

* 重点关注 `src/theme_trading/scanner/` 下的 daily scan、buy point、routing、pending、market/theme/sell 相关模块。
* 重点关注 `src/theme_trading/cli/daily_scan.py` 和 `src/theme_trading/cli/render_daily_scan.py` 的 CLI 参数与文案。
* 重点关注 `docs/trading-system/trading-reference.md` 中通用入场规则与主线/卖出规则。
* 需要确认当前 `trade_date` 在不同模块中是否混用了“扫描基准日”“确认日”“执行日”。
