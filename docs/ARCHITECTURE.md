# ARCHITECTURE — 系统架构

## 一句话

定时器拉 OKX K 线 → pandas 算指标 → 信号规则判定 → 飞书机器人提醒。

## 数据流

```
                  ┌──────────────────┐
                  │  config/         │
                  │  symbols.yaml    │  ─── watchlist
                  │  signals.yaml    │  ─── rule switches
                  └────────┬─────────┘
                           │
                           ▼
                  ┌──────────────────┐
                  │ runner/scheduler │  APScheduler cron
                  │ (阶段 4)         │  每个 (symbol, bar) 一个 job
                  └────────┬─────────┘
                           │
                           ▼
              ┌────────────────────────┐
              │  runner/pipeline       │  单次完整流水线
              │  (阶段 4)              │
              └─┬────────┬───────────┬─┘
                │        │           │
                ▼        ▼           ▼
        ┌────────┐ ┌──────────┐ ┌──────────┐
        │ data/  │ │indicators│ │ signals/ │
        │okx_    │→│moving_avg│→│ rules    │
        │client  │ │dot_locator│ │loader   │
        │(阶段1) │ │(阶段 2)   │ │(阶段 3) │
        └───┬────┘ └──────────┘ └────┬─────┘
            │                         │
            ▼                         ▼
        ┌────────┐               ┌──────────────┐
        │ data/  │               │ notifier/    │
        │cache/  │               │ feishu       │
        │parquet │               │ + dedup      │
        └────────┘               │ (阶段 5)     │
                                 └──────┬───────┘
                                        │
                                        ▼
                                 飞书自建应用
                                 chat 群消息
```

## 模块职责

| 模块 | 输入 | 输出 | 阶段 |
|---|---|---|---|
| `data/okx_client` | (inst_id, bar, limit) | `pd.DataFrame[ts,o,h,l,c,vol,...,confirm]` | 1 |
| `data/kline_store` | (inst_id, bar, n) | 从 parquet 缓存或 client 补齐的 df | 1 |
| `indicators/moving_average` | `pd.Series` 价格 | SMA/EMA Series | 2 |
| `indicators/dot_locator` | df + period | dot Series（N 根前的 low） | 2 |
| `indicators/__init__.compute_all` | df | df + 9 列指标 | 2 |
| `signals/base` | df + 规则参数 | `Optional[Signal]` | 3 |
| `signals/loader` | `signals.yaml` | 启用的规则实例列表 | 3 |
| `runner/pipeline` | (symbol, bar) | `List[Signal]` | 4 |
| `runner/scheduler` | watchlist | 后台 cron jobs | 4 |
| `notifier/feishu` | `Signal` 列表 | 飞书消息已发 | 5 |
| `notifier/dedup` | `Signal` | 是否首次出现 | 5 |

## 配置流向

- `.env`（不入库）→ `pydantic-settings` → `investment.config.Settings`
- `config/*.yaml`（入库，但 secrets 不放这里）→ 各模块直接 `yaml.safe_load`

## 关键设计决策

1. **不用 ccxt** — OKX 公开 candles 接口很简洁，直接 requests 一行 GET 就能拿数据；ccxt 会引入大量未用模块。如果未来接私有接口（下单、查持仓）再上 ccxt。
2. **不用 talib / pandas-ta** — 用户只要 SMA/EMA + shift，pandas 自己写 5 行就够了，零编译依赖（Windows 上 talib 装起来折腾）。
3. **EMA 用 `adjust=False`** — TradingView 的 `ta.ema` 默认是这个，错了出来的数对不上。
4. **parquet 缓存而不是 SQLite** — 单表时间序列、列式压缩更适合 K 线数据；用 pyarrow 引擎，行数到百万级也很快。
5. **APScheduler 而不是 cron** — 跨平台（用户用 Windows）、可以在 Python 内嵌；如果要做守护进程再外加 systemd / nssm。
6. **lark-oapi 自动管 tenant_access_token** — 不需要手动刷 token，省一堆代码。
7. **dedup 用文件持久化** — 进程重启后不重复发；如果后面规则多了再上 SQLite。

## 已知限制

- OKX `/api/v5/market/candles` 单次最多 300 根；要更老的数据走 `history-candles` + 翻页（阶段 1 实现）。
- 飞书 chat_id 需要机器人入群后才能获取；初次部署是手动步骤。
- 当前不抓 WebSocket，全是 REST 轮询；如果未来要做分钟级、秒级实时性，要重做数据层。
