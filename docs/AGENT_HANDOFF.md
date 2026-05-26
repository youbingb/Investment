# AGENT_HANDOFF — 给接手的 agent 看

**这是接手项目时的第一份文档。** 看完这份你应该能直接开始干活。

---

## 项目是什么

用 Python 把用户长期在 TradingView 用的均线指标（SMA/EMA 20-60-120 + 三个圆点）搬到本地，配合 OKX 数据 + 飞书机器人提醒，做一个**只盯盘不下单**的量化系统。

完整背景看 [../README.md](../README.md) 和 [ARCHITECTURE.md](ARCHITECTURE.md)。
用户原版 Pine Script 在 [PINE_SCRIPT_MAPPING.md](PINE_SCRIPT_MAPPING.md)。

---

## 当前进度

看 [PROGRESS.md](PROGRESS.md)（一张表）。

**目前在哪儿**：阶段 0-6 全部完成。**项目主流程到此完工**。

唯一未完成的收尾：**真实联通测试** —— 用户需要填 `.env` 里的 `FEISHU_APP_ID` / `FEISHU_APP_SECRET` / `FEISHU_CHAT_ID` 并把 `FEISHU_DRY_RUN` 设 `false`，然后跑：

```bash
python scripts/send_test_message.py
```

期望飞书群里收到一条 "Investment 联通测试 ..." 文本。如果失败请看 ERROR 提示是 chat_id / 凭证 / 网络哪一段问题（参考 [EXTERNAL_APIS.md](EXTERNAL_APIS.md) 飞书 §"关键坑"）。

获取凭证的方法在 [EXTERNAL_APIS.md](EXTERNAL_APIS.md) "飞书自建应用发消息" 一节。

阶段 1 已交付：
- OKX V5 REST 客户端 `src/investment/data/okx_client.py`
- K 线本地缓存 `src/investment/data/kline_store.py`
- CLI 入口 `scripts/fetch_history.py`
- 21 项单测全过（`pytest tests/test_okx_client.py`）
- 实测：BTC/ETH 真实数据已成功落到 `data/cache/*.parquet`

阶段 2 已交付：
- `src/investment/indicators/moving_average.py`（`sma` + `ema`，`adjust=False`）
- `src/investment/indicators/dot_locator.py`（`dot_low = low.shift(n)`）
- `src/investment/indicators/__init__.compute_all`（追加 9 列）
- `scripts/compute_once.py` CLI 跑通
- 12 项单测全过，含一条"守门"测试防止 EMA 改回 `adjust=True`

阶段 3 已交付：
- `src/investment/signals/base.py`（`Signal` dataclass + `SignalRule` ABC + 工具方法）
- `src/investment/signals/examples/golden_cross.py`（金叉/死叉）
- `src/investment/signals/examples/dot_pullback.py`（dot 回踩支撑/压力）
- `src/investment/signals/loader.py`（按 yaml 装配启用的规则）
- 16 项单测全过；全套 49 测试全绿

阶段 4 已交付：
- `src/investment/runner/pipeline.py`（`run_pipeline` + `load_watchlist`，全局 client/store 单例，规则错误隔离）
- `src/investment/runner/scheduler.py`（`trigger_for_timeframe` 把 OKX bar 映射成 UTC CronTrigger，`build_scheduler` 注册所有 watchlist job）
- `scripts/run_once.py`（CLI 跑一遍，`--enable-all` 临时启用所有规则）
- 16 项新单测，全套 65 项全过；端到端 `run_once.py --enable-all` 实测可跑

阶段 5 已交付（DRY-RUN 通路）：
- `src/investment/notifier/feishu.py`（`FeishuNotifier`：`from_settings()` 自动降级、retry once、`_do_send` 抛错被吞）
- `src/investment/notifier/dedup.py`（`SignalDedup`：JSON 持久化、LRU 1000、坏文件兜底为空状态）
- `src/investment/runner/pipeline.notify_signals` + `get_notifier` / `get_dedup` 进程级单例
- `src/investment/runner/scheduler._job` 接入 `notify_signals`（去掉了阶段 4 的 TODO）
- `scripts/run_once.py --notify`、`scripts/send_test_message.py`
- 29 项新单测：`tests/test_feishu_notifier.py` (15) + `tests/test_dedup.py` (10) + `tests/test_pipeline.py` 增 4 项；全套 94 测试全绿
- 联通测试待办：用户填 `.env` → 跑 `scripts/send_test_message.py`

阶段 6 已交付：
- `src/investment/runner/backtest.py`：`backtest_rules` 滚动跑每根 confirmed bar；`evaluate_outcomes(result, df, horizons, exit_horizon)` 算 long/short 反号的 horizon return + MFE/MAE + 自动跳 neutral；`backtest_with_returns` 一次跑完
- `BacktestResult` 聚合：`hits_by_rule` / `hits_by_direction`（信号层）+ `stats_by_rule()` / `equity_curve()` / `total_return` / `max_drawdown`（收益层）
- `scripts/backtest.py`：终端三段表（per-rule 胜率/平均·中位收益/MFE-MAE、按方向、资金曲线摘要）；`--horizons` / `--exit-after` / `--csv` 可选
- `scripts/run_forever.py`：守护进程 CLI；启动横幅显示 watchlist / dry-run / 脱敏 chat_id；`--list-jobs` 干跑
- `README.md` 修 UTF-16 乱码 + 重写为快速开始 + systemd / nssm / Docker 部署模板
- `.gitignore` 加 `data/reports/*` 屏蔽回测产物
- 20 项 backtest 单测；全套 114 测试全绿
- 端到端实测：`backtest BTC-USDT 1H --enable-all` 34 笔交易 / 胜率 dot 67.7% golden_cross 33.3% / 累计 -0.26% / 最大回撤 -8.30%（13 天数据）

---

## 用户强约束（必读，别违反）

1. **按 STAGES 顺序连续推进**：用户已明确"写完文档再继续按计划开发"，**不要每阶段都停下问用户**。阶段之间不需要等审批，照着 STAGES.md 一路做下去。只有遇到不可决策的歧义、外部凭证缺失（如飞书 chat_id）、或破坏性操作时才暂停。
2. **每次更改文档化**：CHANGELOG.md 至少要更，相关 docs/*.md 也要同步。
3. **每完成一个小功能立即 commit + push** 到 origin/main。颗粒度小一些（一个文件、一个 bug 修复都可以单独 commit）。commit message 用中文，结尾 `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`。
4. **修了缺陷也要立即 push**。
5. **文档要详细**，因为下一个接手的可能是不同的 agent。

---

## 开始之前 — 环境

| 项 | 值 |
|---|---|
| 操作系统 | Windows 11 |
| Shell | git bash（Unix 语法，不要用 cmd / powershell 写法） |
| Python | 3.10+ |
| 包管理 | `uv sync` 或 `pip install -r requirements.txt` |
| 工作目录 | `G:\Code\Toys\Investment` |
| Git remote | `https://github.com/youbingb/Investment.git`（origin main） |

**装依赖**（首次进入项目时）：
```bash
cd "G:/Code/Toys/Investment"
pip install -r requirements.txt
# 或
uv sync
```

**自检**：
```bash
python -c "import investment; print(investment.__version__)"
```

---

## 进入下一阶段时该做什么

按 [STAGES.md](STAGES.md) 走。

### 收尾任务：阶段 5 真实联通测试（10 分钟，需要用户参与）

1. 拿到飞书 `app_id` / `app_secret` / `chat_id`（步骤见 [EXTERNAL_APIS.md](EXTERNAL_APIS.md)）
2. 编辑 `.env`：
   ```
   FEISHU_APP_ID=cli_xxx
   FEISHU_APP_SECRET=xxx
   FEISHU_CHAT_ID=oc_xxx
   FEISHU_DRY_RUN=false
   ```
3. 跑联通自检：
   ```bash
   python scripts/send_test_message.py
   ```
   飞书群里应该收到 "Investment 联通测试 <UTC ts>"。
4. 真发命中信号联调（可选，命中可遇不可求；想强测时把 signals.yaml 阈值放宽或临时改 dot_pullback 的 max_distance_pct 到 5%）：
   ```bash
   python scripts/run_once.py --enable-all --notify
   ```
   同 bar 再跑一次，飞书应该**不重发**（去重已生效）。

### 长跑投入使用

```bash
# 先确认 cron 配置和 watchlist 都对
python scripts/run_forever.py --list-jobs

# 启动守护（前台阻塞）
python scripts/run_forever.py

# 生产部署：见 README.md 的 systemd / nssm / Docker 模板
```

### 已规划完毕，没有"下一阶段"了

如果用户后续要加功能，可能的方向（按优先级猜测）：

1. **新的信号规则**：放到 `src/investment/signals/examples/` 或 `custom/` 下，继承 `SignalRule`，加到 `REGISTRY` 或 `extra_registry`。`signals.yaml` 加一个 enabled=true 段就能开。详见 [STAGES.md](STAGES.md) 阶段 3 + [PINE_SCRIPT_MAPPING.md](PINE_SCRIPT_MAPPING.md)。**已实现的扩展规则**：
   - `golden_cross` / `dot_pullback` — 阶段 3 原始示例
   - `ma_cluster_breakout` — 双均线交易系统开仓 A（6MA 密集后突破）
   - `ma20_pullback` — 双均线交易系统开仓 B（发散后回踩 20 均线不破）
2. **加 watchlist 标的**：编辑 `config/symbols.yaml`，新增 `- symbol: SOL-USDT` 等。
3. **更细的回测**：现在 `scripts/backtest.py` 只统计命中数，没有"命中后 N 根 K 的收益率"之类的指标。要做的话改 `runner/backtest.py` 加 evaluate-then-track 的逻辑。
4. **WebSocket 行情**：当前是 REST 轮询，最小粒度 1 分钟。要做秒级 / tick 级要重做数据层（参考 OKX V5 WebSocket public channel）。
5. **告警卡片**：现在是纯文本飞书消息。要做卡片就改 `FeishuNotifier.send_text` 或新增 `send_card`，`msg_type="interactive"`。

### 关键模块速查（阶段 6 之后）

- `from investment.notifier.feishu import FeishuNotifier` — `FeishuNotifier.from_settings()` 拿单例
- `from investment.notifier.dedup import SignalDedup` — 持久化去重
- `from investment.runner.pipeline import notify_signals, get_notifier, get_dedup` — pipeline 层统一通知入口
- `from investment.runner.backtest import backtest_with_returns, BacktestResult, SignalOutcome` — 历史回放 + 收益跟踪一次跑完
- `python scripts/run_once.py --enable-all --notify` — 跑一轮 + 推送（dry-run 时不真发）
- `python scripts/run_forever.py` — 长跑守护
- `python scripts/backtest.py BTC-USDT 1H --enable-all --csv data/reports/btc_1h.csv` — 历史回放 + CSV 导出
- `python scripts/send_test_message.py` — 联通自检

### 修了 backtest 但 is_win 返回 numpy 标量的坑

`SignalOutcome.is_win` 现在显式 `bool(r > 0)`，否则 numpy 比较得到的是 `np.True_` / `np.False_`，跟 Python `True is` 测试会断言失败。改新规则的话遵循这个习惯。

---

## 决策已经做完的事（不要重新讨论）

- ✅ 交易所：OKX（不是 Binance / Bybit）
- ✅ 监控对：BTC-USDT、ETH-USDT（在 `config/symbols.yaml`）
- ✅ 时间周期：1H、4H 起步
- ✅ 通知：飞书自建应用（不是 webhook 机器人）
- ✅ 不做自动下单
- ✅ 不上 ccxt / talib / pandas-ta
- ✅ EMA 算法用 `adjust=False`

完整决策记录在 [ARCHITECTURE.md](ARCHITECTURE.md) "关键设计决策" 段。

---

## 已知坑 / TODO

- [x] ~~Windows 下中文输出乱码~~ — 已在阶段 1 修复（logger 启动时强制 UTF-8）
- [x] ~~Windows pip 用 GBK 解码 requirements.txt 中文注释失败~~ — 已删除中文注释
- [x] ~~阶段 5 飞书 chat_id 获取文档~~ — 已在 EXTERNAL_APIS.md 写清楚
- [ ] **阶段 5 联通测试待跑**：用户填齐 FEISHU_* 凭证后，跑 `python scripts/send_test_message.py` 验证真发链路
- [ ] OKX 在某些 IP 段（国内裸连）需要走 HK 节点或代理；目前实测网络正常
- [ ] Windows 下 LF/CRLF 换行符警告很多，可以加 `.gitattributes` 治本（优先级低）
- [ ] 阶段 6 的回测脚本只是简易统计，不是完整回测框架

---

## 常用命令速查

```bash
# 跑测试
pytest

# 静态检查
ruff check src/ tests/

# 格式化
ruff format src/ tests/

# 装依赖
pip install -r requirements.txt

# 看 git 状态
git status
git log --oneline -10

# commit + push 一次
git add <files>
git commit -m "..."
git push origin main
```
