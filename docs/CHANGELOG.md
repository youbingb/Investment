# CHANGELOG

每行记录一次有意义的改动。文档微调（typo、格式）不入此表。

## 2026-05-26 — 阶段 6 完成（长跑 + 简易回测）

- `src/investment/runner/backtest.py`：`backtest_rules(df, rules)` 滚动跑每根 confirmed bar；warmup 默认 125（最长均线/dot 120 + 5）；rule 抛错被吞不影响其他规则
- `src/investment/runner/__init__.py`：导出 `backtest_rules` / `BacktestResult`
- `scripts/backtest.py`：CLI 入口，`--start/--end` 限时间窗、`--enable-all`、`--limit-show N` 控制明细行数
- `scripts/run_forever.py`：守护进程 CLI 包装，启动横幅显示 watchlist / dry-run / 脱敏 chat_id；`--list-jobs` 干跑模式
- `tests/test_backtest.py`：8 项 — warmup 跳过、不足时 0 评估、未收盘跳过、空规则、聚合、错误隔离
- `README.md`：从 UTF-16 LE 修成 UTF-8；重写为快速开始 + 常用命令 + 项目结构 + systemd/nssm/Docker 部署模板
- 全套 `pytest tests/` 102 项全过
- 端到端实测：`backtest.py BTC-USDT 1H --enable-all` 在 13 天 309 根历史上跑出 34 次命中

## 2026-05-26 — 阶段 5 完成（飞书提醒，DRY-RUN 通路）

- `src/investment/notifier/feishu.py`：`FeishuNotifier` — `from_settings()` 工厂，凭证不全自动降级 dry-run；真发路径包一次重试，失败 ERROR 不抛
- `src/investment/notifier/dedup.py`：`SignalDedup` — `(symbol, tf, rule, bar_ts)` 去重键 → JSON 持久化到 `data/cache/sent_signals.json`，LRU 上限 1000；坏 JSON 退化为空状态
- `src/investment/notifier/__init__.py`：暴露 `FeishuNotifier` / `SignalDedup`
- `src/investment/runner/pipeline.py`：`notify_signals(signals)` 把通知 + 去重打包；`get_notifier` / `get_dedup` 进程级单例；`reset_notifier_singletons` 测试钩子
- `src/investment/runner/scheduler.py`：`_job` 命中后调 `notify_signals`，去掉了阶段 4 的 TODO 占位
- `scripts/run_once.py`：`--notify` 开关，一轮扫完统一推送
- `scripts/send_test_message.py`：联通自检 CLI（dry-run 也可跑）
- `tests/test_feishu_notifier.py`：15 项 — dry-run 自动降级、retry-once、`_do_send` 异常 / 失败响应、content 必须是 JSON 字符串守门
- `tests/test_dedup.py`：10 项 — 跨实例落盘、LRU 淘汰、损坏文件兜底、自建父目录
- `tests/test_pipeline.py`：+4 项 — `notify_signals` 首次发 / 同 bar 去重 / 失败不入 dedup / 空列表
- 全套 `pytest tests/` 94 项全过
- ⚠ 联通测试未做：`.env` 还没填 `FEISHU_APP_ID` / `FEISHU_APP_SECRET` / `FEISHU_CHAT_ID`，目前所有真发路径都走 dry-run。凭证齐备后跑 `python scripts/send_test_message.py` 验证

## 2026-05-26 — 阶段 4 完成（调度器）

- `src/investment/runner/pipeline.py`：`run_pipeline` 串 fetch → compute → signals；`load_watchlist` 展开 symbols.yaml；`PipelineResult` / `WatchItem` dataclass；全局 client/store 单例
- `src/investment/runner/scheduler.py`：`trigger_for_timeframe` 把 OKX bar 映射成 UTC CronTrigger；`build_scheduler` 注册所有 watchlist job；`misfire_grace_time=120` 容忍 2 分钟内补跑；命中处留好阶段 5 接飞书的位置
- `scripts/run_once.py`：CLI 跑一遍所有组合，`--enable-all` 临时启用所有内置规则；端到端实测 4 个组合扫描完毕
- `tests/test_pipeline.py`：16 项新单测（load_watchlist、run_pipeline 规则隔离、4 类 trigger 映射 + 5 个非法 bar）
- 全套 `pytest tests/` 65 项全过

## 2026-05-26 — 阶段 3 完成（信号引擎）

- `src/investment/signals/base.py`：`Signal` frozen dataclass + `SignalRule` ABC，工具方法 `confirmed` / `last_two_confirmed`
- `src/investment/signals/examples/golden_cross.py`：fast 上/下穿 slow（默认 ema20 vs sma60）
- `src/investment/signals/examples/dot_pullback.py`：当前 low 接近 dot 线（默认 dot60、阈值 0.5%）
- `src/investment/signals/loader.py`：按 yaml `enabled=true` 装配规则；未知规则 / 配置异常都只 WARNING
- `tests/test_signals.py`：16 项单测覆盖两个规则的命中/未命中边界 + loader 兜底
- 全套 `pytest tests/` 49 项全过

## 2026-05-26 — 阶段 2 完成（均线指标层）

- `src/investment/indicators/moving_average.py`：`sma` + `ema`（`ewm(adjust=False)`，TradingView ta.ema 兼容）
- `src/investment/indicators/dot_locator.py`：`dot_low(low, n) = low.shift(n)`（Pine Script `bl[N]` 等价）
- `src/investment/indicators/__init__.py`：`compute_all(df)` 给 df 追加 sma/ema/dot 各 3 个周期共 9 列
- `scripts/compute_once.py`：CLI 端到端 (`python scripts/compute_once.py BTC-USDT 1H --n 300`)
- `tests/test_indicators.py`：12 项单测，含 EMA adjust=False 守门测试
- 端到端实测：BTC-USDT 1H × 200 根，9 个指标都给出合理数值

## 2026-05-26 — 阶段 1 完成（OKX 数据层）

- `src/investment/config.py`：pydantic-settings 读 .env，OKX + Feishu + Log 三组配置 + `get_settings` lru_cache 单例
- `src/investment/logger.py`：loguru 控制台彩色输出 + `_force_utf8_console` 修 Windows 中文乱码
- `src/investment/data/okx_client.py`：OKX V5 REST 客户端（`fetch_candles` + `fetch_history_candles` + 自动重试）
- `src/investment/data/kline_store.py`：parquet 缓存 + `get_or_fetch` 自动补齐
- `scripts/fetch_history.py`：CLI 入口（`python scripts/fetch_history.py BTC-USDT 1H 500`）
- `tests/test_okx_client.py`：21 项单测，monkeypatch 拦截 requests，覆盖 parse / validate / retry
- 实测：BTC-USDT 1H × 100 根、ETH-USDT 4H × 50 根都已成功落 parquet
- 修 `requirements.txt` 删除中文注释，避免 Windows pip GBK 解码失败

## 2026-05-26 — 阶段 0 完成（项目骨架）

- 初始化项目骨架：`pyproject.toml` + `requirements.txt` + `.env.example` + `.gitignore`
- 建立 `src/investment/` 子包目录（data / indicators / signals / notifier / runner）
- 建立 `config/symbols.yaml`（默认 BTC-USDT、ETH-USDT @ 1H+4H）与 `config/signals.yaml` 占位
- 建立 `docs/` 8 份文档（PROGRESS / STAGES / ARCHITECTURE / AGENT_HANDOFF / EXTERNAL_APIS / PINE_SCRIPT_MAPPING / CHANGELOG）
- 修复 `.gitignore` 把 `data/cache/.gitkeep` 也屏蔽掉的小问题
