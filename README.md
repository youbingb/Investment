# Investment

加密货币均线盯盘 + 飞书提醒系统。

把用户长期在 TradingView 用的[均线指标 Pine Script](docs/PINE_SCRIPT_MAPPING.md)（SMA/EMA 20-60-120 + 三个圆点位移）搬到本地，配合 OKX V5 公开行情数据 + 飞书机器人提醒，做一个**只盯盘不下单**的轻量量化系统。

**当前阶段 0-6 已交付。** 详情见 [docs/PROGRESS.md](docs/PROGRESS.md)。

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

---

## 项目结构

```
src/investment/
  data/         # OKX REST 客户端 + parquet 缓存
  indicators/   # SMA / EMA / dot 计算（Pine Script 复刻）
  signals/      # 规则抽象 + 内置规则（金叉、dot 回踩）
  runner/       # pipeline / scheduler / backtest
  notifier/     # FeishuNotifier + SignalDedup
config/         # symbols.yaml（watchlist） + signals.yaml（规则开关）
scripts/        # CLI 入口（fetch / compute / run / backtest / send_test_message）
tests/          # pytest 单测，>100 项
data/cache/     # parquet K 线缓存 + sent_signals.json 去重状态
docs/           # 所有文档（AGENT_HANDOFF 是接手项目的第一份）
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
