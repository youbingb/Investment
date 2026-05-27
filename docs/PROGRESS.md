# PROGRESS — 阶段完成度看板

> 状态图例：⬜ 未开始 / 🔄 进行中 / ✅ 已完成 / ⏸ 暂停 / ❌ 已废弃
>
> 每个阶段结束时必须更新这份文档。详细的目标/产出/验收看 [STAGES.md](STAGES.md)。

| 阶段 | 内容 | 状态 | 备注 |
|---|---|---|---|
| 0 | 项目骨架 + 文档骨架 | ✅ | 2026-05-26 完成 |
| 1 | OKX 行情数据层（REST + parquet 缓存） | ✅ | 2026-05-26 完成；BTC/ETH 实测可拉数据 |
| 2 | 均线指标层（复刻 Pine Script） | ✅ | 2026-05-26 完成；12 项单测全过；端到端 BTC-USDT 1H × 200 跑通 |
| 3 | 信号引擎框架（含 2 个示例规则） | ✅ | 2026-05-26 完成；16 项单测全过 |
| 4 | 调度器（APScheduler 轮询 → pipeline） | ✅ | 2026-05-26 完成；65 项全套单测全过；run_once 实测扫 4 个组合 |
| 5 | 飞书提醒（lark-oapi 自建应用） | ✅ | 2026-05-26 完成（DRY-RUN 通路）；94 项全套单测全过。联通测试待用户填 .env 后跑 send_test_message.py |
| 6 | 长跑模式 + 简易回测脚本（可选） | ✅ | 2026-05-26 完成 + 增强 + 可视化；118 项全套单测全过；backtest 实测 BTC-USDT 1H 13 天 34 笔；Streamlit 仪表盘已上线 |
| 7 | 模拟交易系统（纸上交易） | ✅ | 2026-05-28 完成；PaperAccount + TradeExecutor + 风控 + 持久化 + CLI；37 项新单测全绿 |

---

## 最新一次更新

- **2026-05-28** — 阶段 7 完成（模拟交易系统）。`trader/order.py`（Order / Position / Trade 数据结构，可 JSON 序列化）、`trader/paper_account.py`（PaperAccount：余额管理、开仓/平仓、加仓均价、止损止盈检查、原子写入 JSON 持久化、快照/重置）、`trader/executor.py`（TradeExecutor：信号→下单、反向信号先平旧仓、风控检查——最大持仓/symbol 限制/规则过滤/方向过滤、自动计算止损止盈价）、`config/trading.yaml`（仓位大小/上下限/止损止盈百分比/最大持仓/规则过滤/方向过滤）、`pipeline.py` 新增 `execute_trades()` + `get_account()`/`get_executor()` 单例、`scripts/paper_trade.py` CLI（`--enable-all`/`--status`/`--trades`/`--run-forever`/`--reset`）、37 项新单测（`test_paper_account.py` 22 项 + `test_executor.py` 15 项）全绿。`README.md` 更新项目结构和常用命令表。

- **2026-05-26** — 双均线交易系统两条新规则（来自 YouTube 视频 `a6kCJroORaI`）。`signals/examples/ma_cluster_breakout.py`（6 条均线缠绕后向上/向下突破）+ `signals/examples/ma20_pullback.py`（趋势中首次回踩 20 均线触而不破），都注册到 `signals/loader.REGISTRY`，`config/signals.yaml` 加默认条目（enabled=false）。+16 项新单测，全套 134 项全绿。实测 BTC-USDT 1H：`ma_cluster_breakout` 赔率 3.43、`ma20_pullback` 胜率 25%；BTC-USDT 4H：`ma20_pullback` 胜率 57.7% —— 跟视频"胜率 30-40%、赔率 ≥ 1:3"的描述高度吻合。视频字幕和原始 Pine Script 描述存档在 `.cache/yt/`。

- **2026-05-26** — 阶段 6.6（盈亏比 + Streamlit 可视化）。`runner/backtest.py.stats_by_rule` 新增 avg_win / avg_loss / payoff_ratio（赔率）/ profit_factor（盈亏比），边界（零笔/全胜/全负）走 `_ratio_pos_over_negabs` 统一映射 NaN/inf/0；`scripts/backtest.py` 表头扩到 11 列；新增 `scripts/dashboard.py` Streamlit 仪表盘（sidebar 选 symbol/tf/规则/时间窗，主区域：5 头部指标 + NAV+回撤 + 规则统计表 + K 线+long/short 散点 + exit_return 直方图，plotly 出图）；`pyproject.toml` / `requirements.txt` 加 `viz` 可选依赖（streamlit≥1.30、plotly≥5.18）。+4 项单测，全套 118 项全绿。Playwright headless 端到端烟测通过。

- **2026-05-26** — 阶段 6 增强（完整历史回测）。`runner/backtest.py` 加 `SignalOutcome` + `evaluate_outcomes` + 聚合（胜率 / 平均·中位收益 / MFE-MAE / equity / drawdown）；`scripts/backtest.py` 升级到终端三段表 + `--horizons` / `--exit-after` / `--csv` 选项；`.gitignore` 屏蔽 `data/reports/*`。+12 项新单测，全套 114 项全绿。实测 BTC-USDT 1H 缓存：dot_pullback 胜率 67.7%、golden_cross 33.3%、累计简单收益 -0.26%、最大回撤 -8.30%。

- **2026-05-26** — 阶段 6 完成。`runner/backtest.py`（backtest_rules + BacktestResult）、`scripts/backtest.py` CLI（实测 BTC-USDT 1H 309 根 → 34 命中）、`scripts/run_forever.py` 守护进程 CLI（含启动横幅 + `--list-jobs`）、`README.md` 重写为快速开始 + 部署模板（systemd / nssm / Docker），顺手修复 README 的 UTF-16 LE 乱码。8 项新单测，全套 102 项全绿。项目主流程**到此完工**。剩余收尾工作：用户填 .env 凭证后跑联通自检 `send_test_message.py`。

- **2026-05-26** — 阶段 5 完成（DRY-RUN 通路）。`notifier/feishu.py`（FeishuNotifier + retry once + 凭证不全自动降级 dry-run）、`notifier/dedup.py`（JSON 持久化、LRU 1000、坏文件兜底）、`runner/pipeline.notify_signals` + 单例工厂、`scheduler._job` 接入、`run_once.py --notify`、`scripts/send_test_message.py` 联通自检。29 项新单测，全套 94 项全过。当前 `.env` 中 FEISHU_* 未填，所有真发都走 dry-run；用户填完凭证后跑 `python scripts/send_test_message.py` 验证联通即可关闭阶段 5。

- **2026-05-26** — 阶段 4 完成。`runner/pipeline.py`、`scripts/run_once.py`、`runner/scheduler.py` 落地。16 项新单测，全套 65 测试全绿。`python scripts/run_once.py --enable-all` 端到端扫 4 个组合（BTC/ETH × 1H/4H）正常返回"无命中"。下一步进入阶段 5（飞书提醒），开始前需要用户填 `.env`。

- **2026-05-26** — 阶段 3 完成。`signals/base.py`（Signal + SignalRule ABC）、`signals/examples/{golden_cross,dot_pullback}.py`、`signals/loader.py`（yaml 装配）落地。16 项单测全过；全套 49 测试全绿。下一步进入阶段 4（调度器）。

- **2026-05-26** — 阶段 2 完成。`indicators/moving_average.py`、`indicators/dot_locator.py`、`indicators/__init__.compute_all` 三件套；`scripts/compute_once.py` CLI 跑通；12 项单测全过（含一条守门测试，防止 EMA 被改成 adjust=True）。下一步进入阶段 3（信号引擎）。

- **2026-05-26** — 阶段 1 完成。OKX REST client + KlineStore parquet 缓存 + fetch_history CLI 都已落地，21 项单测全过。实测拉 BTC-USDT 1H × 100 根、ETH-USDT 4H × 50 根都成功。顺手修了 Windows 终端 UTF-8 乱码问题。下一步进入阶段 2（均线指标）。

- **2026-05-26** — 阶段 0 完成。项目目录、依赖、配置、占位代码、8 份文档骨架全部就绪。
