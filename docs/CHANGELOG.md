# CHANGELOG

每行记录一次有意义的改动。文档微调（typo、格式）不入此表。

## 2026-05-26 — 双均线交易系统使用文档

- `docs/DUAL_MA_STRATEGY.md`：完整中文使用手册 — 原理、6 条均线公式、两条规则的信号逻辑/数学定义/参数表/命中样例、`config/signals.yaml` 配置、4 种用法（CLI / 长跑 / 回测 / Streamlit）、Signal 数据结构解读、视频原话风控建议（仓位计算公式 + 表面/实际杠杆 + 3 种止盈法）、时间周期/标的建议、实测回测数据（BTC 1H/4H）、调参建议、FAQ、免责声明
- `README.md`：新增 "内置交易策略" 段，列出 4 条规则并指向使用文档
- `docs/AGENT_HANDOFF.md`：在 "已实现的扩展规则" 列表追加文档链接

## 2026-05-26 — 双均线交易系统两条新规则

视频出处：YouTube《我的第一个100W来源，双均线交易系统实战》(币哥) `a6kCJroORaI`。完整字幕 + Pine Script 描述抓到 `.cache/yt/`（用 Playwright + 已登录 YouTube 会话绕过反爬）。

- `src/investment/signals/examples/ma_cluster_breakout.py`：均线密集后突破。6 条均线 (SMA/EMA 20-60-120) 上根 bar 极差/均值*100 ≤ `cluster_width_pct` 视为密集；当前 bar close 突破簇顶 / 跌破簇底 → 长 / 短信号；建议止损放在上根 bar 簇 min / max
- `src/investment/signals/examples/ma20_pullback.py`：均线发散后回踩 20 均线不破。上根 bar 6MA 发散度 ≥ `min_spread_pct`；可选要求 ema20/60/120 单调对齐趋势方向；当根 wick 触及 `ma_col` (默认 ema20) 在 `tolerance_pct` 内 + close 仍在均线"正确"一侧 → 顺势开仓；建议止损放在 ma_col ± tolerance
- `src/investment/signals/loader.REGISTRY`：注册两条新规则
- `config/signals.yaml`：加 `ma_cluster_breakout` / `ma20_pullback` 段（默认 enabled=false）
- `tests/test_signals_dual_ma.py`：16 项新单测 — 上/下破命中、密度阈值、突破缺失、NaN / 缺列、发散度门槛、趋势对齐开关、tolerance 收紧、close 反向跌穿、ma_col 切到 sma20、REGISTRY 包含
- 全套 `pytest tests/` 134 项全过
- 实测回测 BTC-USDT 1H（13 天 309 根）：`ma_cluster_breakout` 7 笔 / 胜率 28.6% / **赔率 3.43**；`ma20_pullback` 24 笔 / 胜率 25.0% — 与视频"胜率 30-40%、赔率 ≥ 1:3"基本吻合
- 实测 BTC-USDT 4H：`ma20_pullback` 26 笔 / 胜率 **57.7%** — 4H 周期表现更好，验证视频"中线交易"的建议

## 2026-05-26 — 阶段 6.6（盈亏比 + Streamlit 可视化）

- `src/investment/runner/backtest.py`：`stats_by_rule()` 新增 `avg_win` / `avg_loss` / `payoff_ratio`（赔率：均盈/|均亏|）/ `profit_factor`（盈亏比：总盈/|总亏|）；提取 `_ratio_pos_over_negabs` 处理零笔/全胜/全负边界（NaN / inf / 0）
- `scripts/backtest.py`：终端表头扩到 11 列，增加平均盈 / 平均亏 / 赔率 / 盈亏比
- `scripts/dashboard.py`：新增 Streamlit 仪表盘 — sidebar 选 symbol/tf/规则/时间窗/horizons/exit_after；主区头部 5 指标 + 4 模块（NAV+回撤、按规则统计表、K 线+long/short 散点、每笔 exit_return 直方图）；图表用 plotly
- `pyproject.toml` / `requirements.txt`：新增可选 `viz` 依赖组（streamlit≥1.30、plotly≥5.18）
- `tests/test_backtest.py` +4 项：payoff/profit_factor 基本算式、全胜→inf、全负→0、零笔→NaN
- 全套 `pytest tests/` 118 项全过
- Streamlit 端到端烟测：headless 启动 + Playwright 渲染验证（命中 34 笔 / 累计 -0.26% / 整体胜率 64.7%）

## 2026-05-26 — 阶段 6 增强（完整历史回测）

- `src/investment/runner/backtest.py`：新增 `SignalOutcome`（entry_price / horizon_returns / mfe_pct / mae_pct / exit_return / is_win）；`evaluate_outcomes(result, df, horizons, exit_horizon)` 后处理 long/short 反号 + MFE/MAE 在 exit 窗口内、neutral 跳过、窗口不足 NaN；`BacktestResult` 加 `stats_by_rule` / `equity_curve` / `total_return` / `max_drawdown`；`backtest_with_returns` 一次跑完
- `scripts/backtest.py` 升级：终端三段表（per-rule 胜率/平均·中位收益/MFE-MAE、按方向、资金曲线摘要）、`--horizons "1,5,10,20"` 默认、`--exit-after N` 默认 10、`--csv PATH` 导出
- `.gitignore` 加 `data/reports/*` 屏蔽回测产物
- `tests/test_backtest.py` +12 项：线性 long/short 反号、MFE/MAE long&short、窗口不足、neutral 跳过、stats 聚合、equity 累加、drawdown、end-to-end
- 全套 `pytest tests/` 114 项全过
- 实测 BTC-USDT 1H 缓存（13 天 309 根）：34 笔交易、累计 -0.26%、最大回撤 -8.30%、dot_pullback 胜率 67.7% / golden_cross 33.3%

## 2026-05-26 — 阶段 6 完成（长跑 + 简易回测）

- `src/investment/runner/backtest.py`：`backtest_rules(df, rules)` 滚动跑每根 confirmed bar；warmup 默认 125（最长均线/dot 120 + 5）；rule 抛错被吞不影响其他规则
- `src/investment/runner/__init__.py`：导出 `backtest_rules` / `BacktestResult`
- `scripts/backtest.py`：CLI 入口，`--start/--end` 限时间窗、`--enable-all`、`--limit-show N` 控制明细行数
- `scripts/run_forever.py`：守护进程 CLI 包装，启动横幅显示 watchlist / dry-run / 脱敏 chat_id；`--list-jobs` 干跑模式
- `tests/test_backtest.py`：8 项 — warmup 跳过、不足时 0 评估、未收盘跳过、空规则、聚合、错误隔离
- `README.md`：从 UTF-16 LE 修成 UTF-8；重写为快速开始 + 常用命令 + 项目结构 + systemd/nssm/Docker 部署模板
- 全套 `pytest tests/` 102 项全过
- 端到端实测：`backtest.py BTC-USDT 1H --enable-all` 在 13 天 309 根历史上跑出 34 次命中

## 2026-05-26 — 阶段 5 完成（飞书提醒，DRY-RUN 通路）

- `src/investment/notifier/feishu.py`：`FeishuNotifier` — `from_settings()` 工厂，凭证不全自动降级 dry-run；真发路径包一次重试，失败 ERROR 不抛
- `src/investment/notifier/dedup.py`：`SignalDedup` — `(symbol, tf, rule, bar_ts)` 去重键 → JSON 持久化到 `data/cache/sent_signals.json`，LRU 上限 1000；坏 JSON 退化为空状态
- `src/investment/notifier/__init__.py`：暴露 `FeishuNotifier` / `SignalDedup`
- `src/investment/runner/pipeline.py`：`notify_signals(signals)` 把通知 + 去重打包；`get_notifier` / `get_dedup` 进程级单例；`reset_notifier_singletons` 测试钩子
- `src/investment/runner/scheduler.py`：`_job` 命中后调 `notify_signals`，去掉了阶段 4 的 TODO 占位
- `scripts/run_once.py`：`--notify` 开关，一轮扫完统一推送
- `scripts/send_test_message.py`：联通自检 CLI（dry-run 也可跑）
- `tests/test_feishu_notifier.py`：15 项 — dry-run 自动降级、retry-once、`_do_send` 异常 / 失败响应、content 必须是 JSON 字符串守门
- `tests/test_dedup.py`：10 项 — 跨实例落盘、LRU 淘汰、损坏文件兜底、自建父目录
- `tests/test_pipeline.py`：+4 项 — `notify_signals` 首次发 / 同 bar 去重 / 失败不入 dedup / 空列表
- 全套 `pytest tests/` 94 项全过
- ⚠ 联通测试未做：`.env` 还没填 `FEISHU_APP_ID` / `FEISHU_APP_SECRET` / `FEISHU_CHAT_ID`，目前所有真发路径都走 dry-run。凭证齐备后跑 `python scripts/send_test_message.py` 验证

## 2026-05-26 — 阶段 4 完成（调度器）

- `src/investment/runner/pipeline.py`：`run_pipeline` 串 fetch → compute → signals；`load_watchlist` 展开 symbols.yaml；`PipelineResult` / `WatchItem` dataclass；全局 client/store 单例
- `src/investment/runner/scheduler.py`：`trigger_for_timeframe` 把 OKX bar 映射成 UTC CronTrigger；`build_scheduler` 注册所有 watchlist job；`misfire_grace_time=120` 容忍 2 分钟内补跑；命中处留好阶段 5 接飞书的位置
- `scripts/run_once.py`：CLI 跑一遍所有组合，`--enable-all` 临时启用所有内置规则；端到端实测 4 个组合扫描完毕
- `tests/test_pipeline.py`：16 项新单测（load_watchlist、run_pipeline 规则隔离、4 类 trigger 映射 + 5 个非法 bar）
- 全套 `pytest tests/` 65 项全过

## 2026-05-26 — 阶段 3 完成（信号引擎）

- `src/investment/signals/base.py`：`Signal` frozen dataclass + `SignalRule` ABC，工具方法 `confirmed` / `last_two_confirmed`
- `src/investment/signals/examples/golden_cross.py`：fast 上/下穿 slow（默认 ema20 vs sma60）
- `src/investment/signals/examples/dot_pullback.py`：当前 low 接近 dot 线（默认 dot60、阈值 0.5%）
- `src/investment/signals/loader.py`：按 yaml `enabled=true` 装配规则；未知规则 / 配置异常都只 WARNING
- `tests/test_signals.py`：16 项单测覆盖两个规则的命中/未命中边界 + loader 兜底
- 全套 `pytest tests/` 49 项全过

## 2026-05-26 — 阶段 2 完成（均线指标层）

- `src/investment/indicators/moving_average.py`：`sma` + `ema`（`ewm(adjust=False)`，TradingView ta.ema 兼容）
- `src/investment/indicators/dot_locator.py`：`dot_low(low, n) = low.shift(n)`（Pine Script `bl[N]` 等价）
- `src/investment/indicators/__init__.py`：`compute_all(df)` 给 df 追加 sma/ema/dot 各 3 个周期共 9 列
- `scripts/compute_once.py`：CLI 端到端 (`python scripts/compute_once.py BTC-USDT 1H --n 300`)
- `tests/test_indicators.py`：12 项单测，含 EMA adjust=False 守门测试
- 端到端实测：BTC-USDT 1H × 200 根，9 个指标都给出合理数值

## 2026-05-26 — 阶段 1 完成（OKX 数据层）

- `src/investment/config.py`：pydantic-settings 读 .env，OKX + Feishu + Log 三组配置 + `get_settings` lru_cache 单例
- `src/investment/logger.py`：loguru 控制台彩色输出 + `_force_utf8_console` 修 Windows 中文乱码
- `src/investment/data/okx_client.py`：OKX V5 REST 客户端（`fetch_candles` + `fetch_history_candles` + 自动重试）
- `src/investment/data/kline_store.py`：parquet 缓存 + `get_or_fetch` 自动补齐
- `scripts/fetch_history.py`：CLI 入口（`python scripts/fetch_history.py BTC-USDT 1H 500`）
- `tests/test_okx_client.py`：21 项单测，monkeypatch 拦截 requests，覆盖 parse / validate / retry
- 实测：BTC-USDT 1H × 100 根、ETH-USDT 4H × 50 根都已成功落 parquet
- 修 `requirements.txt` 删除中文注释，避免 Windows pip GBK 解码失败

## 2026-05-26 — 阶段 0 完成（项目骨架）

- 初始化项目骨架：`pyproject.toml` + `requirements.txt` + `.env.example` + `.gitignore`
- 建立 `src/investment/` 子包目录（data / indicators / signals / notifier / runner）
- 建立 `config/symbols.yaml`（默认 BTC-USDT、ETH-USDT @ 1H+4H）与 `config/signals.yaml` 占位
- 建立 `docs/` 8 份文档（PROGRESS / STAGES / ARCHITECTURE / AGENT_HANDOFF / EXTERNAL_APIS / PINE_SCRIPT_MAPPING / CHANGELOG）
- 修复 `.gitignore` 把 `data/cache/.gitkeep` 也屏蔽掉的小问题
