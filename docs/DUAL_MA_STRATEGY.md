# 双均线交易系统使用文档

> 把币哥（YouTube 频道）的《双均线交易系统》落地到本项目的实战手册。
>
> 视频原片：<https://www.youtube.com/watch?v=a6kCJroORaI>
> 视频字幕 + 原始 Pine Script 留档于 `.cache/yt/`（本机，未入库）。

---

## 1. 这是什么

把 6 条均线 (SMA/EMA 周期 20、60、120) 组合成一个 "双均线" 簇，靠肉眼可识别的 **均线密集** 与 **均线发散** 两个形态来发现入场点。两套开仓方法分别对应：

| 方法 | 项目里的规则名 | 触发条件简述 |
|---|---|---|
| A 均线密集后突破 | `ma_cluster_breakout` | 6 条均线缠绕在一起 → 收盘价向上/向下脱离簇 |
| B 均线发散后回踩 20 均线不破 | `ma20_pullback` | 6 条均线已经拉开 → 当根 K 线影线触及 20 均线，但收盘没有有效突破 |

策略特征：

- **胜率低（30-40%）、赔率高（≥ 1:3）**：止损小、止盈大
- **反人性**：大部分时间在止损，需要严格遵守计划
- **所见即所得**：不用判断 RSI/MACD/布林带，看均线和 K 线就够
- 适用：BTC、ETH、SOL 等流动性大的主流标的
- 周期：5m/15m（短线）、1H/4H（中线）、日/周（长线）都可用

> **重要**：本项目只盯盘 + 推送提醒，**不会自动下单**。所有"止损价/仓位/杠杆"由你自己在交易所执行。

---

## 2. 前置条件

| 项 | 要求 |
|---|---|
| 操作系统 | Windows / macOS / Linux 都行 |
| Python | 3.10+ |
| 网络 | 能访问 `www.okx.com`（拉 K 线）；国内裸连可能需要 HK 节点 |
| 飞书（可选） | 拿到飞书自建应用 `app_id` / `app_secret` / `chat_id`，否则跑 dry-run 模式 |

装依赖：

```bash
cd "G:/Code/Toys/Investment"
pip install -r requirements.txt
# 想看 Streamlit 仪表盘就再加一行
pip install -e .[viz]
```

如果还没看过项目本身，先扫一眼这两份：
- [README.md](../README.md) — 快速开始 / 常用命令
- [docs/AGENT_HANDOFF.md](AGENT_HANDOFF.md) — 项目当前进度

---

## 3. 5 分钟跑起来

```bash
# 1) 拉 BTC-USDT 1H × 500 根 K 线落 parquet
python scripts/fetch_history.py BTC-USDT 1H 500

# 2) 看一眼指标算出来什么样（最后 10 行）
python scripts/compute_once.py BTC-USDT 1H

# 3) 启用双均线规则（编辑 config/signals.yaml，把两条 enabled 改成 true）
#    或者用 --enable-all 一次性开所有规则（包括另外两条示例）

# 4) 扫一遍 watchlist，不推送
python scripts/run_once.py --enable-all

# 5) 推送到飞书（FEISHU_DRY_RUN=true 时只打印到 stdout）
python scripts/run_once.py --enable-all --notify

# 6) 历史回测看胜率 / 赔率 / 资金曲线
python scripts/backtest.py BTC-USDT 1H --enable-all

# 7) Streamlit 可视化（先 pip install -e .[viz]）
streamlit run scripts/dashboard.py
```

---

## 4. 规则 A：`ma_cluster_breakout` — 均线密集后突破

### 4.1 信号逻辑

只看最末两根 **已收盘** 的 K 线（confirmed bar）。

1. **上根 bar 必须处于"密集态"**：6 条均线最大值与最小值之差占均值的百分比 ≤ `cluster_width_pct`
2. **当前 bar 突破**：
   - 多：上根 close ≤ 上根簇顶（即上根 close 还在簇里或下方），当前 close > 当前簇顶 × (1 + `breakout_buffer_pct`/100)
   - 空：上根 close ≥ 上根簇底，当前 close < 当前簇底 × (1 - `breakout_buffer_pct`/100)

### 4.2 数学定义

```
prev_max  = max(SMA20, SMA60, SMA120, EMA20, EMA60, EMA120)   # 上根 bar
prev_min  = min(...)
prev_avg  = mean(...)
prev_pct  = (prev_max - prev_min) / prev_avg * 100

if prev_pct ≤ cluster_width_pct:        # 上根处于密集态
    if prev_close ≤ prev_max and last_close > last_max * (1 + buf):
        → LONG，建议止损 = prev_min
    elif prev_close ≥ prev_min and last_close < last_min * (1 - buf):
        → SHORT，建议止损 = prev_max
```

### 4.3 参数详解

| 参数 | 默认 | 说明 |
|---|---|---|
| `enabled` | `false` | 开关 |
| `cluster_width_pct` | `0.6` | 6MA 极差/均值 *100 ≤ 此值视为密集。**越小越苛刻**：0.3 = 极度紧密；1.0 = 比较宽松 |
| `breakout_buffer_pct` | `0.0` | 突破时 close 需超出簇顶/簇底的额外百分比。0 = 紧贴 close 就算；0.1 = 必须高/低出 0.1% 才算 |

### 4.4 命中信号长这样

```
[BTC-USDT 1H] 均线密集后上破：6MA密度=0.459% ≤ 0.6%，
close=76774.7000 > 簇顶=77274.6783。建议止损 77640.8803
```

字段：
- `6MA密度` — 上根 bar 的 6 条均线极差/均值 (%)
- `簇顶` / `簇底` — 当前 bar 6 条均线的 max / min
- `建议止损` — 上根 bar 簇 min（多） / max（空）

### 4.5 什么时候不会触发

- 上根 6 条均线已经拉开（密度 > 阈值）→ 不是"密集"
- 当前 close 还在簇内 → 没破出去
- 6 条均线里任一为 NaN（K 线少于 120 根，前面还在 warmup）

---

## 5. 规则 B：`ma20_pullback` — 均线发散后回踩 20 均线不破

### 5.1 信号逻辑

1. **上根 bar 必须处于"发散态"**：6 条均线极差/均值 ≥ `min_spread_pct`
2. **趋势方向明确**（默认强校验）：
   - 上升：`ema20 > ema60 > ema120` 且 close > 20 均线
   - 下降：`ema20 < ema60 < ema120` 且 close < 20 均线
3. **当根 K 线影线触及 20 均线**：
   - 上升趋势：`low` ∈ `[ma20 × (1 - tolerance), ma20 × (1 + tolerance)]` 且 close 收回均线上方 → 多
   - 下降趋势：`high` ∈ 同区间 且 close 收回均线下方 → 空

### 5.2 数学定义

```
prev_spread = (max(6MA) - min(6MA)) / mean(6MA) * 100   # 上根 bar
if prev_spread < min_spread_pct: skip

ma   = last[ma_col]                  # ma_col 默认 ema20
tol  = tolerance_pct / 100
low_band  = ma * (1 - tol)
high_band = ma * (1 + tol)

# 多
if uptrend and last_close > ma and low_band ≤ last_low ≤ high_band:
    → LONG，建议止损 = low_band

# 空
if downtrend and last_close < ma and low_band ≤ last_high ≤ high_band:
    → SHORT，建议止损 = high_band
```

### 5.3 参数详解

| 参数 | 默认 | 说明 |
|---|---|---|
| `enabled` | `false` | 开关 |
| `ma_col` | `ema20` | 用哪条 20 均线。可选 `ema20` / `sma20` |
| `tolerance_pct` | `0.3` | 影线距 20 均线在 ±此值内视为"触碰"。**越小越苛刻** |
| `min_spread_pct` | `1.0` | 上根 bar 6MA 发散度门槛。低于此值视为还在密集，不触发 |
| `require_trend_align` | `true` | `true` 强制 ema20/60/120 单调；`false` 只看 close 在 ma_col 哪一侧 |

### 5.4 命中信号长这样

```
[BTC-USDT 4H] 回踩 ema20 不破（多）：6MA发散=2.94% ≥ 1.0%，
low=80621.2000 触及 ema20=80436.5334，close=80675.7000 收回均线上方。
建议止损 80195.2238
```

字段：
- `6MA发散` — 上根 bar 6 条均线的极差/均值 (%)
- 触及方向：多时是 `low ≈ ma`，空时是 `high ≈ ma`
- `建议止损` — `ma × (1 ± tolerance)`

### 5.5 什么时候不会触发

- 上根 6 均线还密集（发散度 < `min_spread_pct`）→ 趋势不明确，跳过
- `require_trend_align=true` 时 ema20/60/120 没单调 → 跳过
- 当根影线距 20 均线偏离超过 `tolerance_pct` → 没触碰到位
- 当根 close 反向跌穿/突破了 20 均线 → 不算 "不破"

---

## 6. 配置 `config/signals.yaml`

完整开关在这里。两条新规则默认 `enabled: false`，需要手动改成 `true`：

```yaml
rules:
  # 双均线交易系统 · 开仓方法 A
  ma_cluster_breakout:
    enabled: true                # 改这里
    cluster_width_pct: 0.6
    breakout_buffer_pct: 0.0

  # 双均线交易系统 · 开仓方法 B
  ma20_pullback:
    enabled: true                # 改这里
    ma_col: ema20
    tolerance_pct: 0.3
    min_spread_pct: 1.0
    require_trend_align: true

notify:
  dedup_window_bars: 3           # 同一规则在 N 根 K 线内只推一次
```

改完文件后：
- `run_once.py` / `run_forever.py` 重启 → 立即生效
- `backtest.py` 用 `--enable-all` 时无视 `enabled`，直接全开

---

## 7. 使用场景

### 7.1 命令行扫一遍当下行情（适合手动盯盘）

```bash
python scripts/run_once.py --enable-all
```

扫一遍 `config/symbols.yaml` 里所有标的 × 时间周期，命中的信号打印到 stdout。

带 `--notify` 还会推飞书（凭证不全自动 dry-run）：

```bash
python scripts/run_once.py --enable-all --notify
```

### 7.2 长跑守护（自动盯盘 + 飞书提醒）

```bash
# 干跑：看一下注册了多少个 cron job
python scripts/run_forever.py --list-jobs

# 真跑：前台阻塞
python scripts/run_forever.py
```

每个 K 线收盘后自动跑一遍 → 命中 → 通过飞书机器人推到指定群。生产部署模板（systemd / nssm / Docker）见 [README.md](../README.md)。

### 7.3 历史回测（看策略在过去靠不靠谱）

```bash
# 单一标的、单一周期、全规则
python scripts/backtest.py BTC-USDT 1H --enable-all

# 限定时间窗（UTC，含两端）
python scripts/backtest.py BTC-USDT 4H --enable-all --start 2026-01-01 --end 2026-04-30

# 自定义 horizons（持仓 N 根 K 线后的收益）+ exit 周期
python scripts/backtest.py BTC-USDT 1H --enable-all --horizons 1,3,5,10 --exit-after 5

# 导明细到 CSV
python scripts/backtest.py BTC-USDT 1H --enable-all --csv data/reports/btc_1h.csv
```

输出 5 段：
1. 头部 — 时间窗 / 总根数 / 命中数
2. 按规则统计 — 胜率 / 平均收益 / 赔率 / 盈亏比 / MFE / MAE
3. 按方向统计 — long / short / neutral 命中数
4. 资金曲线 — 起止 NAV / 最高 / 最低 / 累计 / 最大回撤
5. 最近 N 条命中明细

### 7.4 Streamlit 可视化仪表盘

```bash
pip install -e .[viz]                    # 首次需要
streamlit run scripts/dashboard.py
```

浏览器自动打开 `http://localhost:8501`。Sidebar 选 symbol / 周期 / 规则 / 时间窗 / horizons / exit。主区有 5 个头部指标 + 4 个图表（NAV+回撤、规则统计、K 线散点、收益直方图）。

---

## 8. 看懂信号消息

`Signal` 数据结构：

```python
Signal(
    symbol     = "BTC-USDT",
    timeframe  = "1H",
    rule_name  = "ma_cluster_breakout",
    direction  = "long",                 # long / short / neutral
    bar_ts     = Timestamp("2026-05-22 14:00+00"),
    price      = 76774.70,               # 信号 K 线的 close
    message    = "[BTC-USDT 1H] 均线密集后下破：…",
    extra      = {
        "cluster_width_pct": 0.459,
        "cluster_top":   77274.68,
        "cluster_bottom": 76398.92,
        "suggested_stop": 77640.88,      # ← 实战可以直接拿这个
    },
)
```

回测 / 飞书消息里展示的就是 `message`，但下游脚本（比如想接 API 直接下单）可以从 `extra.suggested_stop` 拿到建议止损价。

---

## 9. 风控建议（视频原话整理）

项目不下单，但下面是视频里讲的实战配套规则。**自己手动执行的时候照这个来**：

### 9.1 仓位计算公式

```
仓位数量 = 每次最大可亏金额 / |开仓价 - 止损价|
```

例：本金 149 USDT，每笔最多亏 10 USDT；BTC 当前 60000，止损 59700（差 300）：

```
仓位 = 10 / (60000 - 59700) = 0.0333 BTC ≈ 仓位价值 2000 USDT
```

哪怕止损了也只亏 10 USDT，跟你用 1 倍还是 100 倍杠杆都没关系。

### 9.2 杠杆 — "表面" vs "实际"

- **表面杠杆**：交易所选的那个数字（1× / 5× / 100×）
- **实际杠杆** = 仓位价值 / 本金

例上面：149 本金，仓位价值 2000 → 实际杠杆 = 13.4×。

**只要保证仓位价值远小于本金，表面杠杆开多少不影响最大亏损。** 短线小资金可以开高杠杆（保证金占用小、剩余资金安全垫大），中长线必须低杠杆。

### 9.3 止盈（视频提了 3 种）

| 方法 | 适用 | 说明 |
|---|---|---|
| 固定赔率 | 任何场景 | 开仓时就定好 1:3 / 1:5 / 1:10，到了就走 |
| 上一个均线密集（推荐） | 不破历史新高的标的 | 止盈位放在前一个均线密集区，因为那是市场平均筹码价，自然阻力位 |
| 斐波那契 1.618 / 2.618 | 已突破历史新高的标的 | 用上一轮牛市顶到底拉斐波，反过来看延伸位 |

### 9.4 止损（项目里 extra.suggested_stop 已经给了）

- A 规则（密集突破）：上根 bar 簇的另一侧（多→`prev_min`，空→`prev_max`）
- B 规则（20 均线回踩）：`ma × (1 ± tolerance_pct/100)`

---

## 10. 时间周期 / 标的建议

| 周期 | 视频称呼 | 信号频次 | 适合人群 |
|---|---|---|---|
| 5m / 15m | 短线 | 每天 1-2 次 | 全职 / 能盯盘 |
| **1H / 4H** | **中线** | **每月 2-3 次** | **大部分人，包括上班族** |
| 日 / 周 | 长线 | 每季 2-3 次 | 长期主义 |

实测：BTC 4H 上 `ma20_pullback` 胜率到了 **57.7%**，远高于 1H 的 25%。**强烈建议先从 4H 玩起。**

标的：视频建议只看 **BTC / ETH / SOL** —— 流动性好、滑点小。其他山寨币也能用，但小币的"均线密集"经常因为成交量稀疏失真。

---

## 11. 实测回测结果

> 本机缓存数据：BTC-USDT 1H × 309 根（约 13 天），BTC-USDT 4H × 302 根（约 50 天）。
> 时间戳是 2026 年 4-5 月。

### BTC-USDT 1H（全规则 `--enable-all`）

| 规则 | 命中 | 胜率 | 平均收益 | 赔率 | 盈亏比 |
|---|---:|---:|---:|---:|---:|
| dot_pullback | 31 | 67.7% | -0.08% | 0.39 | 0.82 |
| **ma20_pullback** | 24 | 25.0% | -0.46% | 0.35 | 0.12 |
| **ma_cluster_breakout** | 7 | 28.6% | +0.11% | **3.43** | 1.37 |
| golden_cross | 3 | 33.3% | +0.69% | 24.37 | 12.18 |

资金曲线：起 1.0000 → 末 0.8943，累计 **-10.57%**，最大回撤 -13.44%。

### BTC-USDT 4H（全规则）

| 规则 | 命中 | 胜率 | 平均收益 | 赔率 | 盈亏比 |
|---|---:|---:|---:|---:|---:|
| **ma20_pullback** | 26 | **57.7%** | -0.20% | 0.54 | 0.73 |
| dot_pullback | 13 | 69.2% | +0.56% | 0.90 | 2.02 |
| golden_cross | 3 | 33.3% | -0.43% | 1.09 | 0.54 |

资金曲线：累计 **+0.90%**，最高 +8.85%（5/13），最低 -11.76%（4/29）。

> **跟视频说的对得上**：胜率 30-40%、赔率 ≥ 1:3。`ma_cluster_breakout` 在 1H 上的 3.43 赔率几乎就是视频说的 "1:3 ~ 1:5"。

---

## 12. 调参建议

### 12.1 收紧 / 放宽密度阈值

`ma_cluster_breakout.cluster_width_pct` 当前 `0.6` 偏松，可以试：

- `0.4` — 信号更少但更"标准"，赔率应该更高
- `0.3` — 极致紧密，可能整月就 1-2 个信号

### 12.2 回踩容忍度

`ma20_pullback.tolerance_pct` 当前 `0.3` 在 1H 偏松，建议：

- 1H：`0.15` ~ `0.2`
- 4H：`0.3` 保持
- 15m：`0.05` ~ `0.1`

### 12.3 趋势对齐

`ma20_pullback.require_trend_align: true`（默认）能过滤掉很多假信号，但也会错过部分震荡市开始的趋势。如果你愿意承担更多假信号换更多入场机会，改 `false`。

### 12.4 不要打开两个规则同 close

A 和 B 是同一套系统的两种入场，**理论上互斥**（密集 vs 发散）。同时启用没问题（它们在不同形态触发），但如果想纯净测试某一种，先单独开。

---

## 13. 常见问题

**Q：为什么有时候命中信号没看到飞书消息？**
A：检查 `.env`：`FEISHU_APP_ID` / `FEISHU_APP_SECRET` / `FEISHU_CHAT_ID` 都要有，且 `FEISHU_DRY_RUN=false`。还不行就跑 `python scripts/send_test_message.py` 单独测联通。

**Q：同一根 K 线信号会被重复推吗？**
A：不会。`SignalDedup` 用 `(symbol, tf, rule_name, bar_ts)` 做去重键，持久化到 `data/cache/sent_signals.json`。

**Q：6 条均线为什么前 120 根 K 线没有信号？**
A：SMA120 / EMA120 需要 120 根 warmup。`backtest_rules` 默认跳过前 125 根。

**Q：能加 SOL 等其他标的吗？**
A：编辑 `config/symbols.yaml` 加一行 `- symbol: SOL-USDT` 即可。

**Q：能加新的时间周期吗？**
A：能。OKX 支持 `1m/3m/5m/15m/30m/1H/2H/4H/6H/12H/1D/1W/1M`，在 `symbols.yaml` 的 `timeframes` 里加就行。但 1m/3m 用本策略意义不大（频次太高、噪声大）。

**Q：策略胜率低 25%，真能赚钱吗？**
A：理论上能，因为赔率高。100 笔交易：25 次赚 3 块 = 75，75 次亏 1 块 = -75，平本。提到 30% 胜率就是 30×3 - 70×1 = +20。**关键是严格执行止损，亏的时候坚决出**。视频里反复强调这点。

**Q：能直接 API 下单吗？**
A：项目目前**不下单**，是有意为之（避免任何自动化资金风险）。如果想自己加，从 `extra.suggested_stop` 拿止损价，加一个新的 `notifier`（比如 `okx_trader.py`）。

**Q：我想保留视频字幕，但 `.cache/` 被 .gitignore 了？**
A：本来就是有意忽略的（不入库）。如果要保留：把 `.cache/yt/transcript.txt` 复制到 `docs/` 下手动命名。

---

## 14. 限制与免责

- 当前回测窗口很短（13-50 天），**不能据此判定长期表现**。想认真评估请自己拉 1 年以上的数据：
  ```bash
  python scripts/fetch_history.py BTC-USDT 4H 5000   # OKX V5 单次上限 300，但 fetch_history 会分页
  ```
- 回测假设无手续费、无滑点，**实盘扣除手续费后结果会更差**。
- 加密货币交易高风险，**可能损失全部本金**。本项目仅为技术演示，不构成任何投资建议。

---

## 15. 相关文档

- [PINE_SCRIPT_MAPPING.md](PINE_SCRIPT_MAPPING.md) — 6 条均线 + 3 个圆点的 Pine Script 原版对照
- [ARCHITECTURE.md](ARCHITECTURE.md) — 数据流 / 模块划分
- [STAGES.md](STAGES.md) — 项目分阶段建设记录
- [EXTERNAL_APIS.md](EXTERNAL_APIS.md) — OKX V5 和飞书自建应用接入细节
- [AGENT_HANDOFF.md](AGENT_HANDOFF.md) — 接手项目时第一份要看的文档
