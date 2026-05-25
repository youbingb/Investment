# STAGES — 分阶段实施规范

每个阶段是一个独立可验证的小功能单元。完成一个阶段必须满足：

1. 验收命令能跑通
2. 涉及的文档已更新（PROGRESS.md / CHANGELOG.md 至少要动）
3. 一次 `git commit` + `git push origin main`
4. AGENT_HANDOFF.md 写明"下一阶段从哪儿开始"

阶段内部允许多次小 commit。

---

## 阶段 0 — 项目骨架 + 文档骨架 ✅

**已完成（2026-05-26）。**

产出：目录、`pyproject.toml`、`requirements.txt`、`.env.example`、`.gitignore`、`config/{symbols,signals}.yaml`、`src/investment/` 各子包 `__init__.py`、8 份 docs。

---

## 阶段 1 — OKX 行情数据层

### 目标
能拉到 OKX 现货 K 线并存到本地 parquet。

### 关键文件
- `src/investment/data/okx_client.py` — REST 封装
- `src/investment/data/kline_store.py` — 本地缓存
- `src/investment/config.py` — pydantic Settings（OKX_BASE_URL、OKX_REQUEST_TIMEOUT 从 .env 读）
- `src/investment/logger.py` — loguru 初始化
- `scripts/fetch_history.py` — CLI 入口
- `tests/test_okx_client.py` — parse 单测

### 设计要点
- `OKXClient.fetch_candles(inst_id, bar, limit, before=None, after=None) -> pd.DataFrame`
  - 列：`ts (UTC pd.Timestamp), open, high, low, close, vol, vol_ccy, vol_ccy_quote, confirm (bool)`
  - **OKX 返回顺序是最新在前，必须 sort_values('ts') 翻正**
  - bar 必须是大写 H/D（`1H` 不是 `1h`）
  - limit 上限 300（不是 1440）
- `KlineStore`：parquet 存到 `data/cache/{inst_id}_{bar}.parquet`，`get_or_fetch(inst, bar, n)` 缺多少补多少
- 错误处理：网络异常 retry 3 次，indent backoff；OKX 业务错误（code != "0"）直接抛
- 详见 [EXTERNAL_APIS.md](EXTERNAL_APIS.md) 的 OKX 一节

### 验收
```bash
python scripts/fetch_history.py BTC-USDT 1H 500
```
1. 控制台打印最近 5 根 K 线（OHLC 数值要跟 OKX 网页对得上）
2. `data/cache/BTC-USDT_1H.parquet` 落盘且行数 == 500
3. `pytest tests/test_okx_client.py` 全绿

---

## 阶段 2 — 均线指标层（复刻 Pine Script）

### 目标
对阶段 1 的 DataFrame 算出 6 条均线 + 3 个圆点值，列名固定。

### 关键文件
- `src/investment/indicators/moving_average.py`
- `src/investment/indicators/dot_locator.py`
- `src/investment/indicators/__init__.py` 导出 `compute_all`
- `scripts/compute_once.py`
- `tests/test_indicators.py`
- `data/samples/btc_1h_sample.csv` — 固定 200 行用作单测断言基线

### 设计要点
- **EMA 用 `pandas.Series.ewm(span=period, adjust=False).mean()`** —— 这是 TradingView 默认行为，跟 `adjust=True` 的算法差很多，错了出来的数对不上
- **Dot 定位**：第 i 行的 dot20 = 第 (i-20) 行的 low；前 20 行为 NaN
  - 等价于 `df['low'].shift(n)`
  - Pine Script 原文是 `bl[20]` 即"20 根前的 low"
- `compute_all(df)` 在 df 上原地新增 9 列：`sma20/60/120, ema20/60/120, dot20/60/120`，返回新 df

### 验收
```bash
python scripts/compute_once.py BTC-USDT 1H
```
输出最新 5 行带全部指标列；数值要跟 TradingView 同周期截图一致（用户自验，差 < 0.01%）。
`pytest tests/test_indicators.py` 全绿。

详见 [PINE_SCRIPT_MAPPING.md](PINE_SCRIPT_MAPPING.md)。

---

## 阶段 3 — 信号引擎框架

### 目标
留信号规则扩展位 + 2 个示例规则。

### 关键文件
- `src/investment/signals/base.py` — `SignalRule` ABC + `Signal` dataclass
- `src/investment/signals/examples/golden_cross.py`
- `src/investment/signals/examples/dot_pullback.py`
- `src/investment/signals/loader.py` — 根据 `config/signals.yaml` 加载启用的规则
- `tests/test_signals.py`

### 设计要点
- `SignalRule.evaluate(df: pd.DataFrame, params: dict) -> Optional[Signal]`
- `Signal` 包含：`symbol, timeframe, rule_name, direction (long/short), bar_ts, price, message`
- 只看**最后一根已收盘 K 线**（即 `confirm == True` 的最末行），避免对未收盘 bar 误报
- 用户自定义规则放 `signals/custom/`（这个目录暂不创建，文档里指明）

### 验收
两个示例规则各有 1 个命中 case + 1 个未命中 case 的单测，全绿。

---

## 阶段 4 — 调度器

### 目标
定时跑完整 pipeline：fetch → compute_all → 所有启用的 rules → 聚合 Signal 列表。

### 关键文件
- `src/investment/runner/pipeline.py` — 单次 pipeline 函数
- `src/investment/runner/scheduler.py` — APScheduler 入口
- `scripts/run_once.py` — `--once` 跑一次就退出

### 设计要点
- 对 `symbols.yaml` 里每个 (symbol, timeframe) 注册 cron：1H 周期 → 每小时第 1 分钟，4H → 每 4 小时第 1 分钟
- pipeline 内部用 loguru 详细打日志
- 本阶段**不连飞书**，只在 stdout 打印 Signal 列表
- 提供"程序内同步调用" API：`from investment.runner.pipeline import run_once; signals = run_once(symbol, bar)`，方便后续测试和飞书联动

### 验收
```bash
python scripts/run_once.py
```
按顺序输出每个 (symbol, timeframe) 的指标命中情况。

---

## 阶段 5 — 飞书提醒

### 目标
阶段 4 的 Signal → 飞书群消息。

### 关键文件
- `src/investment/notifier/feishu.py` — `FeishuNotifier` 类
- `src/investment/notifier/dedup.py` — 去重器（基于 (symbol, timeframe, rule, bar_ts) 键，存 `data/cache/sent_signals.json`）
- `scripts/send_test_message.py` — 飞书联通自检
- 阶段 4 的 pipeline 增加 `--notify` 开关

### 设计要点
- 走 lark-oapi 的 `client.im.v1.message.create`
- `receive_id_type="chat_id"`、`msg_type="text"`、`content='{"text": "..."}'`（content 是 JSON 字符串！）
- 失败重试 1 次；连续失败要打 ERROR 日志但不抛（避免一次飞书故障让调度器死掉）
- `FEISHU_DRY_RUN=true` 时只打印到 stdout
- 详见 [EXTERNAL_APIS.md](EXTERNAL_APIS.md) 飞书一节

### 验收
1. `python scripts/send_test_message.py` → 飞书群收到联通消息
2. 手动制造一根 K 线让 golden_cross 命中，跑 `scripts/run_once.py --notify` → 群里收到 Signal 文本
3. 同 bar 再跑一次，不应该重复发送

---

## 阶段 6 — 长跑 + 收尾（可选）

- `scripts/run_forever.py`：scheduler 守护进程，捕获 SIGINT 优雅退出
- `scripts/backtest.py`：给定 symbol/bar/起止时间，在历史数据上回放 signal rules，统计命中数
- README 补 Windows / Linux 部署说明
