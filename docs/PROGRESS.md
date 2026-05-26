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
| 6 | 长跑模式 + 简易回测脚本（可选） | ✅ | 2026-05-26 完成 + 增强；114 项全套单测全过；backtest 实测 BTC-USDT 1H 13 天 34 笔 / 累计 -0.26% / 回撤 -8.30% |

---

## 最新一次更新

- **2026-05-26** — 阶段 6 增强（完整历史回测）。`runner/backtest.py` 加 `SignalOutcome` + `evaluate_outcomes` + 聚合（胜率 / 平均·中位收益 / MFE-MAE / equity / drawdown）；`scripts/backtest.py` 升级到终端三段表 + `--horizons` / `--exit-after` / `--csv` 选项；`.gitignore` 屏蔽 `data/reports/*`。+12 项新单测，全套 114 项全绿。实测 BTC-USDT 1H 缓存：dot_pullback 胜率 67.7%、golden_cross 33.3%、累计简单收益 -0.26%、最大回撤 -8.30%。
- **2026-05-26** — 阶段 6 完成。`runner/backtest.py`（backtest_rules + BacktestResult）、`scripts/backtest.py` CLI（实测 BTC-USDT 1H 309 根 → 34 命中）、`scripts/run_forever.py` 守护进程 CLI（含启动横幅 + `--list-jobs`）、`README.md` 重写为快速开始 + 部署模板（systemd / nssm / Docker），顺手修复 README 的 UTF-16 LE 乱码。8 项新单测，全套 102 项全绿。项目主流程**到此完工**。剩余收尾工作：用户填 .env 凭证后跑联通自检 `send_test_message.py`。
- **2026-05-26** — 阶段 5 完成（DRY-RUN 通路）。`notifier/feishu.py`（FeishuNotifier + retry once + 凭证不全自动降级 dry-run）、`notifier/dedup.py`（JSON 持久化、LRU 1000、坏文件兜底）、`runner/pipeline.notify_signals` + 单例工厂、`scheduler._job` 接入、`run_once.py --notify`、`scripts/send_test_message.py` 联通自检。29 项新单测，全套 94 项全过。当前 `.env` 中 FEISHU_* 未填，所有真发都走 dry-run；用户填完凭证后跑 `python scripts/send_test_message.py` 验证联通即可关闭阶段 5。
- **2026-05-26** — 阶段 4 完成。`runner/pipeline.py`、`scripts/run_once.py`、`runner/scheduler.py` 落地。16 项新单测，全套 65 测试全绿。`python scripts/run_once.py --enable-all` 端到端扫 4 个组合（BTC/ETH × 1H/4H）正常返回"无命中"。下一步进入阶段 5（飞书提醒），开始前需要用户填 `.env`。
- **2026-05-26** — 阶段 3 完成。`signals/base.py`（Signal + SignalRule ABC）、`signals/examples/{golden_cross,dot_pullback}.py`、`signals/loader.py`（yaml 装配）落地。16 项单测全过；全套 49 测试全绿。下一步进入阶段 4（调度器）。
- **2026-05-26** — 阶段 2 完成。`indicators/moving_average.py`、`indicators/dot_locator.py`、`indicators/__init__.compute_all` 三件套；`scripts/compute_once.py` CLI 跑通；12 项单测全过（含一条守门测试，防止 EMA 被改成 adjust=True）。下一步进入阶段 3（信号引擎）。
- **2026-05-26** — 阶段 1 完成。OKX REST client + KlineStore parquet 缓存 + fetch_history CLI 都已落地，21 项单测全过。实测拉 BTC-USDT 1H × 100 根、ETH-USDT 4H × 50 根都成功。顺手修了 Windows 终端 UTF-8 乱码问题。下一步进入阶段 2（均线指标）。
- **2026-05-26** — 阶段 0 完成。项目目录、依赖、配置、占位代码、8 份文档骨架全部就绪。
