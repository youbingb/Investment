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

**目前在哪儿**：阶段 0、1 完成，**下一步是阶段 2（均线指标层）**。

阶段 1 已交付：
- OKX V5 REST 客户端 `src/investment/data/okx_client.py`
- K 线本地缓存 `src/investment/data/kline_store.py`
- CLI 入口 `scripts/fetch_history.py`
- 21 项单测全过（`pytest tests/test_okx_client.py`）
- 实测：BTC/ETH 真实数据已成功落到 `data/cache/*.parquet`

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

按 [STAGES.md](STAGES.md) 走。下一阶段（**阶段 2 — 均线指标层**）的步骤：

1. 看 STAGES.md "阶段 2" 段的关键文件清单、设计要点、验收方式
2. 看 [PINE_SCRIPT_MAPPING.md](PINE_SCRIPT_MAPPING.md)，那里有用户原 Pine Script 全文和逐行 Python 对照
3. **重要**：EMA 用 `pandas.Series.ewm(span=period, adjust=False).mean()`，**不是 `adjust=True`**，否则数值跟 TradingView 对不上
4. 颗粒度建议：先 commit `moving_average.py`，再 commit `dot_locator.py`，再 commit `compute_all` + `scripts/compute_once.py`，再 commit 单测
5. 阶段 2 验收：
   - `python scripts/compute_once.py BTC-USDT 1H` 打印最近 5 行带 sma20/sma60/sma120/ema20/ema60/ema120/dot20/dot60/dot120 列
   - `pytest tests/test_indicators.py` 全绿
   - 数值与 TradingView 同周期均线一致（用户自验）
   - 更新 PROGRESS.md / CHANGELOG.md / 本文件
6. **不停下，直接进阶段 3**。只有在阶段 5 需要用户填飞书 .env（app_id / app_secret / chat_id）时才必须暂停等用户。

### 阶段 1（已完成）的关键产出，阶段 2 可直接复用：

- `from investment.data.kline_store import KlineStore`：拿带 ts/open/high/low/close 的 DataFrame
- `from investment.data.okx_client import OKXClient`：要新数据时
- `from investment.logger import logger, setup_logger`：日志
- `data/cache/BTC-USDT_1H.parquet`、`data/cache/ETH-USDT_4H.parquet` 已经有缓存数据，可以离线开发

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
