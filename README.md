# Investment

加密货币均线盯盘 + 模拟交易系统。

把用户长期在 TradingView 用的[均线指标 Pine Script](docs/PINE_SCRIPT_MAPPING.md)（SMA/EMA 20-60-120 + 三个圆点位移）搬到本地，配合 OKX V5 公开行情数据 + 飞书机器人提醒 + **模拟交易**（纸上交易，不接入真实交易所）。

**当前阶段 0-7 已交付。** 详情见 [docs/PROGRESS.md](docs/PROGRESS.md)。

---

## 快速开始

```bash
# 1. 装依赖
pip install -r requirements.txt
# 或
uv sync

# 2. 复制环境变量模板并按需填写
cp .env.example .env
# 飞书三件套（FEISHU_APP_ID / FEISHU_APP_SECRET / FEISHU_CHAT_ID）拿到之前
# 把 FEISHU_DRY_RUN 保持 true，所有通知只打印到 stdout 不真发，开发期省心

# 3. 自检
python -c "import investment; print(investment.__version__)"
pytest -q                                                   # 全套单测应全绿
python scripts/run_once.py --enable-all                     # 端到端扫一遍 watchlist

# 4. 拿到飞书凭证后填 .env，验证联通
python scripts/send_test_message.py                         # 飞书群应收到 "Investment 联通测试 ..."
```

---

## 常用命令

| 场景 | 命令 |
|---|---|
| 拉历史 K 线落 parquet | `python scripts/fetch_history.py BTC-USDT 1H 500` |
| 看指标算出来的样子 | `python scripts/compute_once.py BTC-USDT 1H` |
| 跑一轮 watchlist（不发飞书） | `python scripts/run_once.py --enable-all` |
| 跑一轮并推送飞书 | `python scripts/run_once.py --enable-all --notify` |
| 启动长跑守护 | `python scripts/run_forever.py` |
| 守护干跑（只列 job） | `python scripts/run_forever.py --list-jobs` |
| 联通自检 | `python scripts/send_test_message.py` |
| 历史回放（胜率 / 收益 / 盈亏比 / equity） | `python scripts/backtest.py BTC-USDT 1H --enable-all` |
| 回测明细导出 CSV | `python scripts/backtest.py BTC-USDT 1H --enable-all --csv data/reports/btc_1h.csv` |
| 可视化仪表盘（需先装 viz 依赖） | `pip install -e .[viz]` 然后 `streamlit run scripts/dashboard.py` |
| **模拟交易：跑一轮 + 自动下单** | `python scripts/paper_trade.py --enable-all` |
| **模拟交易：查看账户状态** | `python scripts/paper_trade.py --status` |
| **模拟交易：查看交易历史** | `python scripts/paper_trade.py --trades` |
| **模拟交易：持续运行模式** | `python scripts/paper_trade.py --run-forever --enable-all` |
| **模拟交易：重置账户** | `python scripts/paper_trade.py --reset` |

---

## 项目结构

```
src/investment/
  data/         # OKX REST 客户端 + parquet 缓存
  indicators/   # SMA / EMA / dot 计算（Pine Script 复刻）
  signals/      # 规则抽象 + 内置规则（金叉、dot 回踩、均线密集突破、MA20 回踩）
  runner/       # pipeline / scheduler / backtest
  notifier/     # FeishuNotifier + SignalDedup
  trader/       # 模拟交易（PaperAccount + TradeExecutor）  ← 新增
config/
  symbols.yaml  # watchlist（交易对 + 周期）
  signals.yaml  # 信号规则开关与参数
  trading.yaml  # 模拟交易配置（仓位、风控、方向过滤）  ← 新增
scripts/        # CLI 入口（fetch / compute / run / backtest / paper_trade）
tests/          # pytest 单测
data/cache/     # parquet K 线缓存 + sent_signals.json 去重状态
data/paper_account.json  # 模拟账户持久化状态（自动创建）  ← 新增
docs/           # 所有文档（AGENT_HANDOFF 是接手项目的第一份）
```

---

## 模拟交易系统

### 概述

信号引擎产生信号后，自动执行模拟（纸上）交易，不接入真实交易所。用于验证策略的实战表现。

### 功能

- **自动开仓/平仓**：信号命中后自动下单，反向信号先平旧仓再开新仓
- **止损止盈**：可配置百分比，自动监控触发
- **仓位管理**：按账户余额百分比下单，可设上下限
- **风控**：最大持仓数、单 symbol 限制、规则过滤、方向过滤
- **持久化**：账户状态保存到 JSON 文件，重启不丢失
- **多标的同时持仓**：支持 BTC + ETH 等多个标的并行交易

### 配置

编辑 `config/trading.yaml`：

```yaml
enabled: true                    # 是否启用交易
initial_balance: 10000           # 初始余额（USDT）

position:
  size_pct: 0.10                 # 每笔用 10% 余额
  max_amount: 5000               # 单笔上限
  min_amount: 50                 # 单笔下限

risk:
  stop_loss_pct: 3.0             # 止损 3%
  take_profit_pct: 6.0           # 止盈 6%
  max_open_positions: 3          # 最多 3 个同时持仓
  max_positions_per_symbol: 1    # 每个 symbol 最多 1 个持仓
```

### 使用流程

```bash
# 1. 先用回测验证策略
python scripts/backtest.py BTC-USDT 1H --enable-all

# 2. 调整 trading.yaml 参数

# 3. 跑一轮模拟交易
python scripts/paper_trade.py --enable-all

# 4. 查看账户状态
python scripts/paper_trade.py --status

# 5. 持续运行（每 5 分钟扫描一次）
python scripts/paper_trade.py --run-forever --enable-all --interval 5

# 6. 查看交易历史
python scripts/paper_trade.py --trades
```

---

## 部署

### Linux（systemd）

```ini
# /etc/systemd/system/investment.service
[Unit]
Description=Investment scheduler (OKX + Feishu)
After=network-online.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/opt/investment
EnvironmentFile=/opt/investment/.env
ExecStart=/opt/investment/.venv/bin/python scripts/run_forever.py
Restart=on-failure
RestartSec=15

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now investment
sudo journalctl -u investment -f      # 看日志
```

### Windows（nssm）

```powershell
nssm install Investment "C:\Investment\.venv\Scripts\python.exe" "scripts/run_forever.py"
nssm set Investment AppDirectory "C:\Investment"
nssm set Investment AppStdout "C:\Investment\logs\stdout.log"
nssm set Investment AppStderr "C:\Investment\logs\stderr.log"
nssm start Investment
```

NSSM 下载：https://nssm.cc/

### Docker（可选）

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "scripts/run_forever.py"]
```

---

## 内置交易策略

| 规则 | 触发 | 适用 |
|---|---|---|
| `golden_cross` | EMA 上穿/下穿 SMA（经典金叉死叉） | 趋势确认 |
| `dot_pullback` | 当前 K 线 low 接近 dot 圆点 | 支撑/压力回踩 |
| `ma_cluster_breakout` | 6 条均线密集 → 收盘价突破/跌破 | 双均线交易系统 · 开仓方法 A |
| `ma20_pullback` | 6 条均线发散 + 影线触 20 均线不破 | 双均线交易系统 · 开仓方法 B |

**双均线交易系统** 完整使用文档：[docs/DUAL_MA_STRATEGY.md](docs/DUAL_MA_STRATEGY.md) — 含原理、参数、配置、回测、调参、风控建议。

---

## 协作 agent 须知

如果你是接手这个项目的 AI agent，**先看 [docs/AGENT_HANDOFF.md](docs/AGENT_HANDOFF.md)**。
那里写了当前在哪个阶段、约束、决策记录、已知坑。
