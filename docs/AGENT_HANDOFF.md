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

**目前在哪儿**：阶段 0、1、2、3、4 完成，**下一步是阶段 5（飞书提醒）**。

阶段 5 启动前**必须**先让用户填好 `.env` 里的：
- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`
- `FEISHU_CHAT_ID`

获取方法见 [EXTERNAL_APIS.md](EXTERNAL_APIS.md) "飞书自建应用发消息" 一节。

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

按 [STAGES.md](STAGES.md) 走。下一阶段（**阶段 5 — 飞书提醒**）的步骤：

**⚠ 强制暂停点**：开始前确认 `.env` 里已经填了 `FEISHU_APP_ID` / `FEISHU_APP_SECRET` / `FEISHU_CHAT_ID`。如果没填，先停下来向用户说明获取步骤（见 [EXTERNAL_APIS.md](EXTERNAL_APIS.md)），等用户填完再继续。

1. 看 STAGES.md "阶段 5" 段
2. 关键结构：
   - `src/investment/notifier/feishu.py`：`FeishuNotifier(app_id, app_secret).send_text(chat_id, text)`
   - `src/investment/notifier/dedup.py`：基于 (symbol, timeframe, rule, bar_ts) 的去重器，存 `data/cache/sent_signals.json`
   - `scripts/send_test_message.py`：联通自检
   - 阶段 4 的 `scheduler._job` 函数里的 TODO 处接 FeishuNotifier
3. 关键设计：
   - `content` 必须是 JSON 字符串，不是 dict：`content=json.dumps({"text": "..."})`
   - `FEISHU_DRY_RUN=true` 时只打印不发，避免开发时刷群
   - 失败重试 1 次，连续失败 ERROR 但不抛（不让飞书故障带挂 scheduler）
4. 颗粒度建议：先 `feishu.py` + `send_test_message.py` 验证联通，再 `dedup.py`，再接入 scheduler，再单测
5. 阶段 5 验收：
   - `python scripts/send_test_message.py` → 飞书群收到 "Investment 联通测试"
   - 手动构造命中规则跑 `run_once.py --notify` → 飞书收到 Signal
   - 同 bar 再跑一次 → 不重复发
6. 阶段 5 完成后可以继续阶段 6（可选，长跑 + 回测）。

### 阶段 4（已完成）的关键产出，阶段 5 可直接复用：

- `from investment.runner.pipeline import run_pipeline`：跑一次拿 Signal 列表
- `from investment.runner.scheduler import _job` 里有"命中处插入飞书"的占位
- `from investment.config import get_settings`：拿 FEISHU_APP_ID 等
- `from investment.signals.base import Signal`：`sig.dedup_key()` 直接拿去重键

阶段 5 接 scheduler 的最小改动：
```python
# scheduler._job 内
from investment.notifier.feishu import FeishuNotifier
notifier = FeishuNotifier.from_settings()  # 单例
for sig in result.signals:
    notifier.send_text(sig.message)
```

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
- [ ] OKX 在某些 IP 段（国内裸连）需要走 HK 节点或代理；目前实测网络正常
- [ ] 飞书 chat_id 获取目前是手动步骤，阶段 5 文档里要写清楚
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
