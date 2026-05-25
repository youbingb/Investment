# PINE_SCRIPT_MAPPING — 原 Pine Script → Python 对照

## 用户原版 Pine Script

```pinescript
//@version=6
indicator("均线系统", shorttitle="均", overlay=true)

// —— 均线计算
sma20  = ta.sma(close, 20)
sma60  = ta.sma(close, 60)
sma120 = ta.sma(close, 120)

ema20  = ta.ema(close, 20)
ema60  = ta.ema(close, 60)
ema120 = ta.ema(close, 120)

// —— 绘制均线
plot(sma20,  color=color.black,                title="SMA20")
plot(ema20,  color=color.new(color.black, 50), title="EMA20")

plot(sma60,  color=color.blue,                 title="SMA60")
plot(ema60,  color=color.new(color.blue, 50),  title="EMA60")

plot(sma120, color=color.purple,               title="SMA120")
plot(ema120, color=color.new(color.purple, 50),title="EMA120")

// —— 圆点定位
cond    = barstate.islast
bl      = low

moveBar = input.int(0,   title="Move Bar")
x20     = input.int(20,  title="X20 Offset")  + moveBar
x60     = input.int(60,  title="X60 Offset")  + moveBar
x120    = input.int(120, title="X120 Offset") + moveBar

plot(cond ? bl[20]  : na, color=color.new(#FFC40C, 0), linewidth=5,
     offset=-x20,  style=plot.style_circles, title="Dot20")
plot(cond ? bl[60]  : na, color=color.new(#FFC40C, 0), linewidth=5,
     offset=-x60,  style=plot.style_circles, title="Dot60")
plot(cond ? bl[120] : na, color=color.new(#FFC40C, 0), linewidth=5,
     offset=-x120, style=plot.style_circles, title="Dot120")
```

---

## 逻辑解读

1. **6 条均线**：SMA/EMA 三组周期（20、60、120）
2. **3 个圆点**：在"最新一根 K 线（`barstate.islast`）"上，分别画三个圆点；圆点的**位置**通过 `offset=-x20/-x60/-x120` 把它向左平移 20/60/120 根，**圆点的值**则是 `bl[20] / bl[60] / bl[120]`，即 20/60/120 根前那一根的 `low`。

**直观理解**：圆点是"N 根前那根 K 线的最低价"在当前 K 线右侧（视觉上向左偏移到那根 K 线的位置）画了个黄色圆点。常用于看历史支撑位是否被回踩。

---

## 对应到本项目（阶段 2 实现）

| Pine Script | Python | 文件 |
|---|---|---|
| `ta.sma(close, 20)` | `df['close'].rolling(20).mean()` | `indicators/moving_average.py:sma` |
| `ta.ema(close, 20)` | `df['close'].ewm(span=20, adjust=False).mean()` | `indicators/moving_average.py:ema` |
| `bl[20]`（20 根前的 low） | `df['low'].shift(20)` | `indicators/dot_locator.py:dot_low` |
| `barstate.islast` | 在量化系统里**不需要这个 gate**——我们要的是每一根 K 线上都有对应的 dot 值（便于回测、信号判断）。圆点的"只在最新 bar 显示" 是 TradingView 绘图限制，不是逻辑限制。 | — |
| `plot(offset=-x20)` | 仅 UI 显示偏移，本项目不画图，跳过。 | — |
| `input.int(...)` | 在 `config/signals.yaml` 里参数化（如果信号规则需要） | — |

---

## compute_all 的输出列（阶段 2 落实）

```python
df = compute_all(df)
# 新增列：
df['sma20'], df['sma60'], df['sma120']
df['ema20'], df['ema60'], df['ema120']
df['dot20'], df['dot60'], df['dot120']   # 第 i 行的 dot20 = 第 i-20 行的 low
```

前 N 行（N=120）部分指标会是 NaN，这是正常的，信号判定时要跳过。

---

## 验证方法（阶段 2 完成后用户自验）

1. 在 TradingView 上打开 BTC-USDT 1H，挂上用户的 Pine 指标
2. 跑 `python scripts/compute_once.py BTC-USDT 1H`
3. 对照最新已收盘 K 线的 sma20/sma60/sma120/ema20/ema60/ema120 数值，与 TradingView 鼠标悬停在那根 K 线时显示的数值对比
4. 误差应在 0.01% 以内（浮点精度差异）；如果差超过 0.1%，多半是 EMA 用错了 `adjust=True`

---

## 实施状态

✅ **2026-05-26**：阶段 2 完成。
- `sma` / `ema` / `dot_low` / `compute_all` 已落在 `src/investment/indicators/`
- `tests/test_indicators.py` 12 项单测全过，含一条 EMA `adjust=False` 守门测试
- `scripts/compute_once.py BTC-USDT 1H --n 200` 端到端跑通
- TradingView 数值对照由用户在浏览器端自验（截图对比）
