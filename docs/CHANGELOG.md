# CHANGELOG

每行记录一次有意义的改动。文档微调（typo、格式）不入此表。

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
